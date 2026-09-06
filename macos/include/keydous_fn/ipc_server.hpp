#pragma once

#include <atomic>

namespace keydous::fn {

class RuntimeController;

class IPCServer final {
 public:
  explicit IPCServer(RuntimeController& runtime) : runtime_(runtime) {}
  int run(std::atomic<bool>& stop_requested);

 private:
  RuntimeController& runtime_;
};

}  // namespace keydous::fn
