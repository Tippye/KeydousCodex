#include "keydous_fn/runtime_controller.hpp"

#include "keydous_fn/device_discovery.hpp"
#include "keydous_fn/hid_capture.hpp"
#include "keydous_fn/report_state.hpp"
#include "keydous_fn/virtual_hid_bridge.hpp"

#include <chrono>
#include <utility>

namespace keydous::fn {

RuntimeController::RuntimeController() {
  bridge_ = std::make_unique<VirtualHIDBridge>([this](std::string error) {
    std::lock_guard lock(pending_mutex_);
    pending_failure_ = std::move(error);
  });
}

RuntimeController::~RuntimeController() {
  std::string ignored;
  {
    std::lock_guard lock(mutex_);
    (void)disable_locked(ignored, true);
  }
  bridge_->stop();
  bridge_.reset();  // detach dispatcher callbacks while controller mutexes still exist
}

bool RuntimeController::enable(const Configuration& configuration,
                               const ProcessIdentity& controller,
                               std::string& error) {
  std::lock_guard lock(mutex_);
  if (active_) {
    std::string disable_error;
    if (!disable_locked(disable_error, false)) {
      error = disable_error;
      return false;
    }
  }
  last_error_.clear();
  {
    std::lock_guard pending_lock(pending_mutex_);
    pending_failure_.clear();
  }

  std::string discovery_error;
  auto selected = copy_selected_device(configuration.device, discovery_error);
  if (!selected) {
    error = discovery_error;
    last_error_ = error;
    return false;
  }
  CFRelease(selected);

  if (!bridge_->prepare(std::chrono::seconds(8), error)) {
    const auto bridge_status = bridge_->status();
    if (!bridge_status.driver_activated && !bridge_status.driver_version_mismatch) {
      error = "system_extension_approval_required";
    }
    const auto prepare_error = error;
    std::string teardown_error;
    (void)bridge_->terminate_keyboard(std::chrono::seconds(3), teardown_error);
    error = prepare_error;
    last_error_ = error;
    return false;
  }

  reports_ = std::make_unique<ReportState>([this](const Snapshot& snapshot) {
    std::string post_error;
    if (!bridge_->post(snapshot, post_error)) {
      std::lock_guard pending_lock(pending_mutex_);
      pending_failure_ = std::move(post_error);
    }
  });
  reports_->set_mappings({{
      {configuration.source_usage_page, configuration.source_usage},
      {apple_vendor_top_case_page, keyboard_fn_usage},
  }});

  capture_ = std::make_unique<HIDCapture>(
      configuration.device,
      [this](Usage usage, bool down) { reports_->handle(usage, down); });
  if (!capture_->start(error)) {
    reports_->release_all();
    std::string terminate_error;
    (void)bridge_->terminate_keyboard(std::chrono::seconds(3), terminate_error);
    capture_.reset();
    reports_.reset();
    last_error_ = error;
    return false;
  }

  controller_ = controller;
  configuration_ = configuration;
  active_ = true;
  return true;
}

bool RuntimeController::disable(std::string& error) {
  std::lock_guard lock(mutex_);
  return disable_locked(error, false);
}

bool RuntimeController::disable_locked(std::string& error, bool preserve_error) {
  if (capture_) capture_->stop();  // fail open before touching virtual output

  bool release_queued = true;
  if (reports_) {
    reports_->release_all();
    // release_all's sink records a pending failure if the report could not queue.
    std::lock_guard pending_lock(pending_mutex_);
    if (!pending_failure_.empty()) {
      release_queued = false;
      error = pending_failure_;
      pending_failure_.clear();
    }
  }

  std::string terminate_error;
  const bool terminate_acknowledged =
      bridge_->terminate_keyboard(std::chrono::seconds(3), terminate_error);
  capture_.reset();
  reports_.reset();
  controller_.reset();
  configuration_.reset();
  active_ = false;

  if (!terminate_acknowledged) error = terminate_error;
  if (!release_queued || !terminate_acknowledged) {
    if (!preserve_error) last_error_ = error;
    return false;
  }
  if (!preserve_error) last_error_.clear();
  return true;
}

void RuntimeController::fail_open_locked(const std::string& error) {
  if (capture_) capture_->stop();
  if (reports_) reports_->release_all();
  std::string ignored;
  (void)bridge_->terminate_keyboard(std::chrono::seconds(1), ignored);
  capture_.reset();
  reports_.reset();
  controller_.reset();
  configuration_.reset();
  active_ = false;
  last_error_ = error;
  {
    std::lock_guard pending_lock(pending_mutex_);
    pending_failure_.clear();
  }
}

void RuntimeController::tick() {
  std::string failure;
  {
    std::lock_guard pending_lock(pending_mutex_);
    failure = std::exchange(pending_failure_, {});
  }
  std::lock_guard lock(mutex_);
  if (active_ && capture_) {
    if (auto capture_failure = capture_->take_failure(); !capture_failure.empty()) {
      failure = std::move(capture_failure);
    }
  }
  if (active_ && controller_ && !process_identity_is_alive(*controller_)) {
    failure = "controller_disconnected";
  }
  if (active_ && input_monitoring_denied()) {
    failure = "input_permission_revoked";
  }
  if (active_ && !failure.empty()) fail_open_locked(failure);
}

RuntimeStatus RuntimeController::status() {
  tick();
  std::lock_guard lock(mutex_);
  auto status = bridge_->status();
  status.active = active_;
  status.input_captured = capture_ && capture_->captured();
  status.configuration = configuration_;
  std::string discovery_error;
  status.candidates = enumerate_candidates(discovery_error);

  if (active_ && status.input_captured && status.virtual_keyboard_ready) {
    status.state = "active";
    status.message = "Native Fn mapping is active.";
  } else if (!last_error_.empty()) {
    const bool approval = last_error_ == "input_permission_required" ||
                          last_error_ == "input_permission_revoked" ||
                          last_error_ == "system_extension_approval_required";
    status.state = approval ? "requires_approval" : "error";
    status.error_code = last_error_;
    status.message = "Native Fn mapping stopped safely after an error.";
  } else if (!discovery_error.empty()) {
    status.state = "error";
    status.error_code = discovery_error;
    status.message = "USB keyboard discovery is unavailable.";
  } else if (status.driver_version_mismatch) {
    status.state = "error";
    status.error_code = "driver_mismatch";
    status.message = "The installed virtual HID driver version is incompatible.";
  } else if (!status.daemon_connected) {
    status.state = "error";
    status.error_code = "daemon_unavailable";
    status.message = "The virtual HID daemon is unavailable.";
  } else if (!status.driver_activated) {
    status.state = "requires_approval";
    status.error_code = "system_extension_approval_required";
    status.message = "Approve the virtual HID system extension in System Settings.";
  } else if (!status.driver_connected) {
    status.state = "error";
    status.error_code = "driver_unavailable";
    status.message = "The virtual HID system extension is not connected.";
  } else {
    status.state = "ready";
    status.message = "Native Fn support is ready to enable.";
  }
  return status;
}

}  // namespace keydous::fn
