#include "keydous_fn/process_identity.hpp"

#include <libproc.h>

namespace keydous::fn {

std::optional<ProcessIdentity> read_process_identity(std::int32_t pid,
                                                     std::uint32_t expected_uid,
                                                     std::string& error) {
  if (pid <= 1) {
    error = "controller_pid_invalid";
    return std::nullopt;
  }
  struct proc_bsdinfo info{};
  if (proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &info, sizeof(info)) != sizeof(info)) {
    error = "controller_process_unavailable";
    return std::nullopt;
  }
  if (info.pbi_uid != expected_uid) {
    error = "controller_uid_mismatch";
    return std::nullopt;
  }
  return ProcessIdentity{
      .pid = pid,
      .uid = info.pbi_uid,
      .start_seconds = info.pbi_start_tvsec,
      .start_microseconds = info.pbi_start_tvusec,
  };
}

bool process_identity_is_alive(const ProcessIdentity& identity) {
  std::string error;
  const auto current = read_process_identity(identity.pid, identity.uid, error);
  return current && current->start_seconds == identity.start_seconds &&
         current->start_microseconds == identity.start_microseconds;
}

}  // namespace keydous::fn
