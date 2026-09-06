#pragma once

#include <cstdint>
#include <string>

namespace keydous::fn {

struct AuthenticatedPeer final {
  std::uint32_t uid{};
  std::int32_t pid{};
};

std::uint32_t current_console_uid();
bool authenticate_control_peer(int socket, AuthenticatedPeer& peer, std::string& error);

}  // namespace keydous::fn
