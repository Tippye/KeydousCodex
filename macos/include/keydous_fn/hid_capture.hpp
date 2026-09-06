#pragma once

#include "keydous_fn/models.hpp"
#include "keydous_fn/report_state.hpp"

#include <atomic>
#include <condition_variable>
#include <functional>
#include <mutex>
#include <string>
#include <thread>

namespace keydous::fn {

bool input_monitoring_denied();

class HIDCapture final {
 public:
  using EventCallback = std::function<void(Usage, bool)>;

  HIDCapture(DeviceSelection selection, EventCallback callback);
  ~HIDCapture();
  HIDCapture(const HIDCapture&) = delete;
  HIDCapture& operator=(const HIDCapture&) = delete;

  bool start(std::string& error);
  void stop();
  [[nodiscard]] bool captured() const noexcept { return captured_.load(); }
  [[nodiscard]] std::string take_failure();

  // IOHID callbacks enter through these narrow adapters on the capture run loop.
  void on_value(Usage usage, bool down);
  void on_removed();
  void on_io_error();

 private:
  void run();

  DeviceSelection selection_;
  EventCallback callback_;
  std::thread thread_;
  std::mutex mutex_;
  std::condition_variable condition_;
  bool start_complete_{};
  std::string start_error_;
  std::string failure_;
  std::atomic<bool> stop_requested_{};
  std::atomic<bool> captured_{};
  void* run_loop_{};
};

}  // namespace keydous::fn
