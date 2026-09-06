#include "keydous_fn/ipc_server.hpp"

#include "keydous_fn/models.hpp"
#include "keydous_fn/peer_auth.hpp"
#include "keydous_fn/process_identity.hpp"
#include "keydous_fn/runtime_controller.hpp"

#include <libproc.h>
#include <poll.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <string>

namespace keydous::fn {
namespace {

constexpr std::size_t maximum_request_size = 64 * 1024;
constexpr auto request_deadline = std::chrono::seconds(5);
constexpr auto io_poll_slice = std::chrono::milliseconds(100);

bool wait_for_io(int socket, short events,
                 std::chrono::steady_clock::time_point deadline,
                 const std::atomic<bool>& stop_requested) {
  while (!stop_requested.load()) {
    const auto now = std::chrono::steady_clock::now();
    if (now >= deadline) return false;
    const auto remaining = std::chrono::duration_cast<std::chrono::milliseconds>(deadline - now);
    const auto timeout = static_cast<int>(std::min(remaining, io_poll_slice).count());
    pollfd descriptor{.fd = socket, .events = events, .revents = 0};
    const auto result = poll(&descriptor, 1, timeout);
    if (result > 0) return (descriptor.revents & events) != 0;
    if (result < 0 && errno != EINTR) return false;
  }
  return false;
}

bool read_line(int socket, std::string& output,
               const std::atomic<bool>& stop_requested,
               RuntimeController& runtime) {
  output.clear();
  char buffer[4096];
  const auto deadline = std::chrono::steady_clock::now() + request_deadline;
  while (output.size() <= maximum_request_size) {
    runtime.tick();
    if (!wait_for_io(socket, POLLIN, deadline, stop_requested)) return false;
    const auto received = recv(socket, buffer, sizeof(buffer), MSG_DONTWAIT);
    if (received < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR))
      continue;
    if (received <= 0) return false;
    const auto newline = static_cast<const char*>(
        memchr(buffer, '\n', static_cast<std::size_t>(received)));
    if (newline) {
      const auto bytes = static_cast<std::size_t>(newline - buffer);
      if (output.size() + bytes > maximum_request_size) return false;
      output.append(buffer, bytes);
      return !output.empty();
    }
    if (output.size() + static_cast<std::size_t>(received) > maximum_request_size)
      return false;
    output.append(buffer, static_cast<std::size_t>(received));
  }
  return false;
}

bool send_line(int socket, const std::string& value,
               const std::atomic<bool>& stop_requested) {
  std::string framed = value;
  framed.push_back('\n');
  std::size_t sent = 0;
  const auto deadline = std::chrono::steady_clock::now() + request_deadline;
  while (sent < framed.size()) {
    if (!wait_for_io(socket, POLLOUT, deadline, stop_requested)) return false;
    const auto count = send(socket, framed.data() + sent, framed.size() - sent,
                            MSG_NOSIGNAL | MSG_DONTWAIT);
    if (count < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR))
      continue;
    if (count <= 0) return false;
    sent += static_cast<std::size_t>(count);
  }
  return true;
}

bool request_owns_parent(const AuthenticatedPeer& peer, std::int32_t controller_pid) {
  struct proc_bsdshortinfo info{};
  if (proc_pidinfo(peer.pid, PROC_PIDT_SHORTBSDINFO, 0, &info, sizeof(info)) !=
      sizeof(info)) {
    return false;
  }
  return info.pbsi_ppid == controller_pid;
}

int create_server_socket(std::uint32_t console_uid) {
  const int server = socket(AF_UNIX, SOCK_STREAM, 0);
  if (server < 0) return -1;
  sockaddr_un address{};
  address.sun_family = AF_UNIX;
  strlcpy(address.sun_path, helper_socket_path, sizeof(address.sun_path));
  unlink(helper_socket_path);
  if (bind(server, reinterpret_cast<sockaddr*>(&address), sizeof(address)) != 0 ||
      chown(helper_socket_path, console_uid, 0) != 0 ||
      chmod(helper_socket_path, S_IRUSR | S_IWUSR) != 0 || listen(server, 8) != 0) {
    close(server);
    unlink(helper_socket_path);
    return -1;
  }
  return server;
}

}  // namespace

int IPCServer::run(std::atomic<bool>& stop_requested) {
  auto socket_owner = current_console_uid();
  if (socket_owner == UINT32_MAX || socket_owner == 0) return 2;
  const int server = create_server_socket(socket_owner);
  if (server < 0) return 3;

  while (!stop_requested.load()) {
    runtime_.tick();
    const auto console_uid = current_console_uid();
    if (console_uid != socket_owner) {
      std::string ignored;
      (void)runtime_.disable(ignored);
      if (console_uid != UINT32_MAX && console_uid != 0) {
        socket_owner = console_uid;
        (void)chown(helper_socket_path, socket_owner, 0);
      }
    }

    pollfd descriptor{.fd = server, .events = POLLIN, .revents = 0};
    const auto result = poll(&descriptor, 1, 250);
    if (result <= 0 || !(descriptor.revents & POLLIN)) continue;
    const int client = accept(server, nullptr, nullptr);
    if (client < 0) continue;
    timeval timeout{.tv_sec = 5, .tv_usec = 0};
    setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(client, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));

    AuthenticatedPeer peer;
    std::string auth_error;
    if (!authenticate_control_peer(client, peer, auth_error)) {
      RuntimeStatus status;
      status.state = "error";
      status.error_code = auth_error;
      status.message = "The control client was not authorized.";
      (void)send_line(client, encode_response_json("", false, status), stop_requested);
      close(client);
      continue;
    }

    std::string line;
    if (!read_line(client, line, stop_requested, runtime_)) {
      close(client);
      continue;
    }
    const auto decoded = decode_request_json(line);
    if (!decoded.request) {
      auto status = runtime_.status();
      status.state = "error";
      status.error_code = decoded.error;
      status.message = "The control request was rejected.";
      (void)send_line(client, encode_response_json("", false, status), stop_requested);
      close(client);
      continue;
    }

    const auto& request = *decoded.request;
    bool ok = true;
    std::string operation_error;
    if (request.command == Command::enable) {
      if (!request.controller_pid || !request.configuration ||
          !request_owns_parent(peer, *request.controller_pid)) {
        ok = false;
        operation_error = "controller_parent_mismatch";
      } else {
        auto identity = read_process_identity(*request.controller_pid, peer.uid,
                                              operation_error);
        ok = identity && runtime_.enable(*request.configuration, *identity,
                                         operation_error);
      }
    } else if (request.command == Command::disable) {
      ok = runtime_.disable(operation_error);
    }

    auto status = runtime_.status();
    if (!ok && !operation_error.empty()) {
      status.state = "error";
      status.error_code = operation_error;
      status.message = "The requested native Fn state was not acknowledged.";
    }
    (void)send_line(client, encode_response_json(request.request_id, ok, status),
                    stop_requested);
    close(client);
  }

  std::string ignored;
  (void)runtime_.disable(ignored);
  close(server);
  unlink(helper_socket_path);
  return 0;
}

}  // namespace keydous::fn
