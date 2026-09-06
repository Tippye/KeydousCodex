#include "keydous_fn/virtual_hid_bridge.hpp"
#include "keydous_fn/keyboard_teardown_state.hpp"

#include <pqrs/dispatcher.hpp>
#include <pqrs/hid.hpp>
#include <pqrs/karabiner/driverkit/virtual_hid_device_driver.hpp>
#include <pqrs/karabiner/driverkit/virtual_hid_device_service.hpp>

#include <algorithm>
#include <atomic>
#include <cstdint>

namespace keydous::fn {
namespace service = pqrs::karabiner::driverkit::virtual_hid_device_service;
namespace report = pqrs::karabiner::driverkit::virtual_hid_device_driver::hid_report;

class VirtualHIDBridge::Impl final {
 public:
  explicit Impl(ReadinessLossCallback callback) : loss_callback_(std::move(callback)) {
    pqrs::dispatcher::extra::initialize_shared_dispatcher();
    client_ = std::make_unique<service::client>();
    client_->connected.connect([this] {
      bool initialize = false;
      {
        std::lock_guard lock(mutex_);
        connected_ = true;
        initialize = want_keyboard_;
      }
      condition_.notify_all();
      if (initialize) initialize_keyboard();
    });
    client_->connect_failed.connect([this](const auto&) {
      fail("daemon_unavailable", true);
    });
    client_->closed.connect([this] { fail("daemon_disconnected", true); });
    client_->error_occurred.connect([this](const auto&) {
      // A request error does not necessarily close pqrs' transport. Preserve
      // connection state so a later enable can issue a new initialize request.
      fail("virtual_hid_client_error", false);
    });
    client_->warning_reported.connect([this](const auto&) {
      std::lock_guard lock(mutex_);
      warning_ = "virtual_hid_client_warning";
    });
    client_->driver_activated.connect([this](bool value) {
      bool unexpected_loss = false;
      {
        std::lock_guard lock(mutex_);
        unexpected_loss = driver_activated_ && !value && want_keyboard_ && !terminating_;
        driver_activated_ = value;
      }
      condition_.notify_all();
      if (unexpected_loss) notify_loss("driver_deactivated");
    });
    client_->driver_connected.connect([this](bool value) {
      bool unexpected_loss = false;
      {
        std::lock_guard lock(mutex_);
        unexpected_loss = driver_connected_ && !value && want_keyboard_ && !terminating_;
        driver_connected_ = value;
      }
      condition_.notify_all();
      if (unexpected_loss) notify_loss("driver_disconnected");
    });
    client_->driver_version_mismatched.connect([this](bool value) {
      {
        std::lock_guard lock(mutex_);
        mismatch_ = value;
      }
      condition_.notify_all();
      if (value) notify_loss("driver_mismatch");
    });
    client_->virtual_hid_keyboard_ready.connect([this](bool value) {
      bool unexpected_loss = false;
      {
        std::lock_guard lock(mutex_);
        unexpected_loss = keyboard_.ready() && !value && want_keyboard_ && !terminating_;
        keyboard_.observe_ready(value);
      }
      condition_.notify_all();
      if (unexpected_loss) notify_loss("virtual_keyboard_not_ready");
    });
    client_->async_start();
  }

  ~Impl() {
    stop();
    client_.reset();
    pqrs::dispatcher::extra::terminate_shared_dispatcher();
  }

  bool prepare(std::chrono::milliseconds timeout, std::string& error) {
    {
      std::lock_guard lock(mutex_);
      want_keyboard_ = true;
      keyboard_.mark_requested();
      terminating_ = false;
      fatal_error_.clear();
    }
    if (connected()) initialize_keyboard();

    std::unique_lock lock(mutex_);
    const auto completed = condition_.wait_for(lock, timeout, [this] {
      return keyboard_.ready() || mismatch_ || !fatal_error_.empty();
    });
    if (!completed) {
      error = "virtual_keyboard_ready_timeout";
      return false;
    }
    if (mismatch_) {
      error = "driver_mismatch";
      return false;
    }
    if (!fatal_error_.empty()) {
      error = fatal_error_;
      return false;
    }
    if (!keyboard_.ready()) {
      error = "virtual_keyboard_not_ready";
      return false;
    }
    return true;
  }

  bool post(const Snapshot& snapshot, std::string& error) {
    {
      std::lock_guard lock(mutex_);
      if (!keyboard_.ready() || !client_) {
        error = "virtual_keyboard_not_ready";
        return false;
      }
    }

    const auto keyboard_key_count = std::ranges::count_if(
        snapshot.keyboard, [](auto usage) { return usage < 0xe0 || usage > 0xe7; });
    if (keyboard_key_count > 32 || snapshot.consumer.size() > 32 ||
        snapshot.generic_desktop.size() > 32 ||
        snapshot.apple_vendor_top_case.size() > 32 ||
        snapshot.apple_vendor_keyboard.size() > 32) {
      error = "report_capacity_exceeded";
      return false;
    }

    report::keyboard_input keyboard;
    for (const auto usage : snapshot.keyboard) {
      switch (usage) {
        case 0xe0: keyboard.modifiers.insert(report::modifier::left_control); break;
        case 0xe1: keyboard.modifiers.insert(report::modifier::left_shift); break;
        case 0xe2: keyboard.modifiers.insert(report::modifier::left_option); break;
        case 0xe3: keyboard.modifiers.insert(report::modifier::left_command); break;
        case 0xe4: keyboard.modifiers.insert(report::modifier::right_control); break;
        case 0xe5: keyboard.modifiers.insert(report::modifier::right_shift); break;
        case 0xe6: keyboard.modifiers.insert(report::modifier::right_option); break;
        case 0xe7: keyboard.modifiers.insert(report::modifier::right_command); break;
        default: keyboard.keys.insert(static_cast<std::uint16_t>(usage)); break;
      }
    }
    report::consumer_input consumer;
    for (const auto usage : snapshot.consumer)
      consumer.keys.insert(static_cast<std::uint16_t>(usage));
    report::generic_desktop_input generic_desktop;
    for (const auto usage : snapshot.generic_desktop)
      generic_desktop.keys.insert(static_cast<std::uint16_t>(usage));
    report::apple_vendor_top_case_input top_case;
    for (const auto usage : snapshot.apple_vendor_top_case)
      top_case.keys.insert(static_cast<std::uint16_t>(usage));
    report::apple_vendor_keyboard_input vendor_keyboard;
    for (const auto usage : snapshot.apple_vendor_keyboard)
      vendor_keyboard.keys.insert(static_cast<std::uint16_t>(usage));

    // Each report is the complete held set for its usage page.
    client_->async_post_report(keyboard);
    client_->async_post_report(consumer);
    client_->async_post_report(generic_desktop);
    client_->async_post_report(top_case);
    client_->async_post_report(vendor_keyboard);
    return true;
  }

  bool terminate_keyboard(std::chrono::milliseconds timeout, std::string& error) {
    KeyboardTeardownState::Token initial_revision = 0;
    {
      std::lock_guard lock(mutex_);
      want_keyboard_ = false;
      terminating_ = true;
      const auto token = keyboard_.begin_termination();
      if (!token) {
        terminating_ = false;
        return true;
      }
      initial_revision = *token;
    }
    // Reset first so a held report is cleared even before the device teardown is
    // processed.  Readiness alone is not teardown evidence: connection failures
    // also clear the local readiness flag.
    client_->async_virtual_hid_keyboard_reset();
    client_->async_virtual_hid_keyboard_terminate();
    std::unique_lock lock(mutex_);
    const auto acknowledged = condition_.wait_for(lock, timeout, [this, initial_revision] {
      return keyboard_.acknowledged(initial_revision);
    });
    keyboard_.complete_termination();
    terminating_ = false;
    if (!acknowledged) {
      // Destroying this daemon connection removes its client_entry upstream,
      // which destroys the per-client virtual keyboard and its report state.
      // Reconnect for later status/enable requests, but do not claim an ACK.
      client_->async_stop();
      connected_ = false;
      keyboard_.observe_transport_loss();
      lock.unlock();
      client_->async_start();
      error = "virtual_keyboard_terminate_unacknowledged";
      return false;
    }
    return true;
  }

  void stop() {
    if (!client_) return;
    std::string ignored;
    (void)terminate_keyboard(std::chrono::milliseconds(1500), ignored);
    client_->async_stop();
  }

  RuntimeStatus status() const {
    std::lock_guard lock(mutex_);
    RuntimeStatus status;
    status.daemon_connected = connected_;
    status.driver_activated = driver_activated_;
    status.driver_connected = driver_connected_;
    status.driver_version_mismatch = mismatch_;
    status.virtual_keyboard_ready = keyboard_.ready();
    if (mismatch_) {
      status.error_code = "driver_mismatch";
    } else if (!fatal_error_.empty()) {
      status.error_code = fatal_error_;
    }
    return status;
  }

 private:
  bool connected() const {
    std::lock_guard lock(mutex_);
    return connected_;
  }

  void initialize_keyboard() {
    service::virtual_hid_keyboard_parameters parameters;
    parameters.set_country_code(pqrs::hid::country_code::us);
    client_->async_virtual_hid_keyboard_initialize(parameters);
  }

  void fail(std::string error, bool connection_lost) {
    bool should_notify = false;
    {
      std::lock_guard lock(mutex_);
      if (connection_lost) connected_ = false;
      keyboard_.observe_transport_loss();
      fatal_error_ = error;
      should_notify = want_keyboard_ && !terminating_;
    }
    condition_.notify_all();
    if (should_notify) notify_loss(std::move(error));
  }

  void notify_loss(std::string error) {
    if (loss_callback_) loss_callback_(std::move(error));
  }

  ReadinessLossCallback loss_callback_;
  std::unique_ptr<service::client> client_;
  mutable std::mutex mutex_;
  std::condition_variable condition_;
  bool connected_{};
  bool driver_activated_{};
  bool driver_connected_{};
  bool mismatch_{};
  bool want_keyboard_{};
  bool terminating_{};
  KeyboardTeardownState keyboard_;
  std::string fatal_error_;
  std::string warning_;
};

VirtualHIDBridge::VirtualHIDBridge(ReadinessLossCallback callback)
    : impl_(std::make_unique<Impl>(std::move(callback))) {}
VirtualHIDBridge::~VirtualHIDBridge() = default;
bool VirtualHIDBridge::prepare(std::chrono::milliseconds timeout, std::string& error) {
  return impl_->prepare(timeout, error);
}
bool VirtualHIDBridge::post(const Snapshot& snapshot, std::string& error) {
  return impl_->post(snapshot, error);
}
bool VirtualHIDBridge::terminate_keyboard(std::chrono::milliseconds timeout,
                                          std::string& error) {
  return impl_->terminate_keyboard(timeout, error);
}
void VirtualHIDBridge::stop() { impl_->stop(); }
RuntimeStatus VirtualHIDBridge::status() const { return impl_->status(); }

}  // namespace keydous::fn
