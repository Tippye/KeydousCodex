#pragma once

#include <cstdint>
#include <optional>
#include <string>

namespace keydous::fn {

struct ProcessIdentity final {
  std::int32_t pid{};
  std::uint32_t uid{};
  std::uint64_t start_seconds{};
  std::uint64_t start_microseconds{};
};

std::optional<ProcessIdentity> read_process_identity(std::int32_t pid,
                                                     std::uint32_t expected_uid,
                                                     std::string& error);
bool process_identity_is_alive(const ProcessIdentity& identity);

}  // namespace keydous::fn
