#pragma once

#include "keydous_fn/models.hpp"
#include "keydous_fn/report_state.hpp"

#include <chrono>
#include <condition_variable>
#include <functional>
#include <memory>
#include <mutex>
#include <string>

namespace keydous::fn {

class VirtualHIDBridge final {
 public:
  using ReadinessLossCallback = std::function<void(std::string)>;

  explicit VirtualHIDBridge(ReadinessLossCallback callback);
  ~VirtualHIDBridge();
  VirtualHIDBridge(const VirtualHIDBridge&) = delete;
  VirtualHIDBridge& operator=(const VirtualHIDBridge&) = delete;

  bool prepare(std::chrono::milliseconds timeout, std::string& error);
  bool post(const Snapshot& snapshot, std::string& error);
  bool terminate_keyboard(std::chrono::milliseconds timeout, std::string& error);
  void stop();
  [[nodiscard]] RuntimeStatus status() const;

 private:
  class Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace keydous::fn
