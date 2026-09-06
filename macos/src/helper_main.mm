#include "keydous_fn/ipc_server.hpp"
#include "keydous_fn/runtime_controller.hpp"

#include <atomic>
#include <csignal>
#include <unistd.h>

namespace {
std::atomic<bool> stop_requested;
void handle_signal(int) { stop_requested.store(true); }
}  // namespace

int main() {
  if (geteuid() != 0) return 77;
  std::signal(SIGTERM, handle_signal);
  std::signal(SIGINT, handle_signal);
  std::signal(SIGPIPE, SIG_IGN);
  keydous::fn::RuntimeController runtime;
  keydous::fn::IPCServer server(runtime);
  return server.run(stop_requested);
}
