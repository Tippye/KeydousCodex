#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace keydous::fn {

inline constexpr std::uint32_t protocol_version = 1;
inline constexpr std::uint32_t keydous_vendor_id = 0x3151;
inline constexpr std::uint32_t nj98_product_id = 0x4015;
inline constexpr const char* helper_socket_path =
    "/var/run/keydous-codex-fn-helper.sock";

struct DeviceSelection final {
  std::uint64_t registry_entry_id{};
  std::uint32_t vendor_id{};
  std::uint32_t product_id{};
  std::string transport;
};

struct Configuration final {
  std::uint32_t schema_version{};
  DeviceSelection device;
  std::uint32_t source_usage_page{};
  std::uint32_t source_usage{};
  std::string target;
};

struct DeviceCandidate final {
  std::uint64_t registry_entry_id{};
  std::uint32_t vendor_id{};
  std::uint32_t product_id{};
  std::string product;
  std::string serial_number;
  std::string transport;
};

enum class Command { status, enable, disable };

struct Request final {
  std::uint32_t protocol_version{};
  std::string request_id;
  Command command{Command::status};
  std::optional<Configuration> configuration;
  std::optional<std::int32_t> controller_pid;
};

struct RuntimeStatus final {
  bool daemon_connected{};
  bool driver_activated{};
  bool driver_connected{};
  bool driver_version_mismatch{};
  bool virtual_keyboard_ready{};
  bool input_captured{};
  bool active{};
  std::string state{"error"};
  std::string message;
  std::string error_code;
  std::optional<Configuration> configuration;
  std::vector<DeviceCandidate> candidates;
};

struct DecodeResult final {
  std::optional<Request> request;
  std::string error;
};

struct ConfigDecodeResult final {
  std::optional<Configuration> configuration;
  std::string error;
};

ConfigDecodeResult decode_configuration_json(const std::string& json);
DecodeResult decode_request_json(const std::string& json);
std::string encode_response_json(const std::string& request_id, bool ok,
                                 const RuntimeStatus& status);
std::string encode_status_json(const RuntimeStatus& status);

}  // namespace keydous::fn
