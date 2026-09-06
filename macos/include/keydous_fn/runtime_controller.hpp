#pragma once

#include "keydous_fn/models.hpp"
#include "keydous_fn/process_identity.hpp"

#include <memory>
#include <mutex>
#include <string>

namespace keydous::fn {

class HIDCapture;
class ReportState;
class VirtualHIDBridge;

class RuntimeController final {
 public:
  RuntimeController();
  ~RuntimeController();
  RuntimeController(const RuntimeController&) = delete;
  RuntimeController& operator=(const RuntimeController&) = delete;

  bool enable(const Configuration& configuration,
              const ProcessIdentity& controller,
              std::string& error);
  bool disable(std::string& error);
  RuntimeStatus status();
  void tick();

 private:
  bool disable_locked(std::string& error, bool preserve_error);
  void fail_open_locked(const std::string& error);

  std::mutex mutex_;
  std::unique_ptr<VirtualHIDBridge> bridge_;
  std::unique_ptr<ReportState> reports_;
  std::unique_ptr<HIDCapture> capture_;
  std::optional<ProcessIdentity> controller_;
  std::optional<Configuration> configuration_;
  bool active_{};
  std::string last_error_;
  std::mutex pending_mutex_;
  std::string pending_failure_;
};

}  // namespace keydous::fn
