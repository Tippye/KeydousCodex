#import <Foundation/Foundation.h>

#include "keydous_fn/models.hpp"
#include "keydous_fn/report_state.hpp"

#include <limits>
#include <set>
#include <cerrno>
#include <cstring>
#include <cstdlib>
#include <utility>

namespace keydous::fn {
namespace {

std::string string_from_ns(NSString* value) {
  return value ? std::string(value.UTF8String ?: "") : std::string{};
}

bool exact_keys(NSDictionary* dictionary, const std::set<std::string>& allowed) {
  for (id key in dictionary) {
    if (![key isKindOfClass:NSString.class] || !allowed.contains(string_from_ns(key))) {
      return false;
    }
  }
  return true;
}

bool unsigned_number(id value, std::uint64_t maximum, std::uint64_t& output) {
  if (![value isKindOfClass:NSNumber.class] ||
      CFGetTypeID((__bridge CFTypeRef)value) == CFBooleanGetTypeID() ||
      CFNumberIsFloatType((__bridge CFNumberRef)value)) {
    return false;
  }
  std::int64_t signed_value = 0;
  if (!CFNumberGetValue((__bridge CFNumberRef)value, kCFNumberSInt64Type,
                        &signed_value) ||
      signed_value < 0 || static_cast<std::uint64_t>(signed_value) > maximum) {
    return false;
  }
  output = static_cast<std::uint64_t>(signed_value);
  return true;
}

ConfigDecodeResult decode_configuration_dictionary(NSDictionary* root) {
  ConfigDecodeResult result;
  if (![root isKindOfClass:NSDictionary.class] ||
      !exact_keys(root, {"schemaVersion", "device", "source", "target"})) {
    result.error = "config_shape_invalid";
    return result;
  }

  auto* device = root[@"device"];
  auto* source = root[@"source"];
  if (![device isKindOfClass:NSDictionary.class] ||
      ![source isKindOfClass:NSDictionary.class] ||
      !exact_keys(device, {"registryEntryId", "vendorId", "productId", "transport"}) ||
      !exact_keys(source, {"usagePage", "usage"})) {
    result.error = "config_shape_invalid";
    return result;
  }

  Configuration config;
  std::uint64_t number = 0;
  if (!unsigned_number(root[@"schemaVersion"], UINT32_MAX, number) || number != 1) {
    result.error = "config_version_unsupported";
    return result;
  }
  config.schema_version = static_cast<std::uint32_t>(number);

  id registry_value = device[@"registryEntryId"];
  if (![registry_value isKindOfClass:NSString.class]) {
    result.error = "registry_id_invalid";
    return result;
  }
  NSString* registry = registry_value;
  if (registry.length == 0 || registry.length > 20 ||
      [registry rangeOfCharacterFromSet:
          [NSCharacterSet decimalDigitCharacterSet].invertedSet].location != NSNotFound ||
      ![registry canBeConvertedToEncoding:NSASCIIStringEncoding]) {
    result.error = "registry_id_invalid";
    return result;
  }
  errno = 0;
  char* end = nullptr;
  const auto registry_id = strtoull(registry.UTF8String, &end, 10);
  if (errno == ERANGE || !end || *end != '\0' || registry_id == 0) {
    result.error = "registry_id_invalid";
    return result;
  }
  config.device.registry_entry_id = registry_id;

  if (!unsigned_number(device[@"vendorId"], UINT32_MAX, number) ||
      number != keydous_vendor_id) {
    result.error = "device_vendor_not_allowed";
    return result;
  }
  config.device.vendor_id = static_cast<std::uint32_t>(number);
  if (!unsigned_number(device[@"productId"], UINT32_MAX, number) ||
      number != nj98_product_id) {
    result.error = "device_product_not_allowed";
    return result;
  }
  config.device.product_id = static_cast<std::uint32_t>(number);
  if (![device[@"transport"] isKindOfClass:NSString.class] ||
      ![device[@"transport"] isEqualToString:@"USB"]) {
    result.error = "device_transport_not_allowed";
    return result;
  }
  config.device.transport = "USB";

  if (!unsigned_number(source[@"usagePage"], UINT32_MAX, number) ||
      number != keyboard_page) {
    result.error = "source_usage_page_not_allowed";
    return result;
  }
  config.source_usage_page = static_cast<std::uint32_t>(number);
  if (!unsigned_number(source[@"usage"], UINT32_MAX, number) || number < 4 ||
      number > 0xe7 || number == 0x39) {
    result.error = "source_usage_not_allowed";
    return result;
  }
  config.source_usage = static_cast<std::uint32_t>(number);

  if (![root[@"target"] isKindOfClass:NSString.class] ||
      ![root[@"target"] isEqualToString:@"native_fn"]) {
    result.error = "target_not_allowed";
    return result;
  }
  config.target = "native_fn";
  result.configuration = std::move(config);
  return result;
}

NSDictionary* config_dictionary(const Configuration& config) {
  NSString* transport = [NSString stringWithUTF8String:config.device.transport.c_str()];
  NSString* target = [NSString stringWithUTF8String:config.target.c_str()];
  return @{
    @"schemaVersion" : @(config.schema_version),
    @"device" : @{
      @"registryEntryId" : [NSString stringWithFormat:@"%llu", config.device.registry_entry_id],
      @"vendorId" : @(config.device.vendor_id),
      @"productId" : @(config.device.product_id),
      @"transport" : transport,
    },
    @"source" : @{
      @"usagePage" : @(config.source_usage_page),
      @"usage" : @(config.source_usage),
    },
    @"target" : target,
  };
}

NSDictionary* candidate_dictionary(const DeviceCandidate& candidate) {
  NSString* product = [NSString stringWithUTF8String:candidate.product.c_str()];
  NSString* serial = [NSString stringWithUTF8String:candidate.serial_number.c_str()];
  NSString* transport = [NSString stringWithUTF8String:candidate.transport.c_str()];
  return @{
    @"registryEntryId" : [NSString stringWithFormat:@"%llu", candidate.registry_entry_id],
    @"vendorId" : @(candidate.vendor_id),
    @"productId" : @(candidate.product_id),
    @"product" : product,
    @"serialNumber" : serial,
    @"transport" : transport,
  };
}

NSDictionary* status_dictionary(const RuntimeStatus& status) {
  NSMutableArray* candidates = [NSMutableArray arrayWithCapacity:status.candidates.size()];
  for (const auto& candidate : status.candidates) {
    [candidates addObject:candidate_dictionary(candidate)];
  }
  NSMutableDictionary* result = [@{
    @"schemaVersion" : @1,
    @"state" : [NSString stringWithUTF8String:status.state.c_str()],
    @"active" : @(status.active),
    @"ready" : @(status.state == "ready" || status.state == "active"),
    @"installed" : @YES,
    @"requiresApproval" : @(status.state == "requires_approval"),
    @"message" : [NSString stringWithUTF8String:status.message.c_str()],
    @"daemonConnected" : @(status.daemon_connected),
    @"driverActivated" : @(status.driver_activated),
    @"driverConnected" : @(status.driver_connected),
    @"driverVersionMismatch" : @(status.driver_version_mismatch),
    @"virtualKeyboardReady" : @(status.virtual_keyboard_ready),
    @"inputCaptured" : @(status.input_captured),
    @"candidates" : candidates,
  } mutableCopy];
  if (!status.error_code.empty()) {
    result[@"errorCode"] = [NSString stringWithUTF8String:status.error_code.c_str()];
  }
  if (status.configuration) {
    result[@"configuration"] = config_dictionary(*status.configuration);
  }
  return result;
}

std::string serialize(id object) {
  NSError* error = nil;
  NSData* data = [NSJSONSerialization dataWithJSONObject:object options:0 error:&error];
  if (!data || error) {
    return "{}";
  }
  return std::string(static_cast<const char*>(data.bytes), data.length);
}

}  // namespace

ConfigDecodeResult decode_configuration_json(const std::string& json) {
  @autoreleasepool {
    NSData* data = [NSData dataWithBytes:json.data() length:json.size()];
    NSError* error = nil;
    id root = [NSJSONSerialization JSONObjectWithData:data options:0 error:&error];
    if (error || !root) {
      return {.configuration = std::nullopt, .error = "config_json_invalid"};
    }
    return decode_configuration_dictionary(root);
  }
}

DecodeResult decode_request_json(const std::string& json) {
  @autoreleasepool {
    DecodeResult result;
    NSData* data = [NSData dataWithBytes:json.data() length:json.size()];
    NSError* error = nil;
    id value = [NSJSONSerialization JSONObjectWithData:data options:0 error:&error];
    if (error || ![value isKindOfClass:NSDictionary.class]) {
      result.error = "request_json_invalid";
      return result;
    }
    NSDictionary* root = value;
    if (!exact_keys(root, {"protocolVersion", "requestId", "command", "config", "controllerPid"})) {
      result.error = "request_shape_invalid";
      return result;
    }
    Request request;
    std::uint64_t number = 0;
    if (!unsigned_number(root[@"protocolVersion"], UINT32_MAX, number) || number != protocol_version) {
      result.error = "protocol_version_unsupported";
      return result;
    }
    request.protocol_version = static_cast<std::uint32_t>(number);
    if (![root[@"requestId"] isKindOfClass:NSString.class] ||
        [(NSString*)root[@"requestId"] length] == 0 ||
        [(NSString*)root[@"requestId"] length] > 64) {
      result.error = "request_id_invalid";
      return result;
    }
    request.request_id = string_from_ns(root[@"requestId"]);
    if (![root[@"command"] isKindOfClass:NSString.class]) {
      result.error = "command_invalid";
      return result;
    }
    NSString* command = root[@"command"];
    if ([command isEqualToString:@"status"]) {
      request.command = Command::status;
    } else if ([command isEqualToString:@"disable"]) {
      request.command = Command::disable;
    } else if ([command isEqualToString:@"enable"]) {
      request.command = Command::enable;
      if (![root[@"config"] isKindOfClass:NSDictionary.class]) {
        result.error = "config_required";
        return result;
      }
      auto decoded = decode_configuration_dictionary(root[@"config"]);
      if (!decoded.configuration) {
        result.error = decoded.error;
        return result;
      }
      request.configuration = std::move(decoded.configuration);
      if (!unsigned_number(root[@"controllerPid"], INT32_MAX, number) || number <= 1) {
        result.error = "controller_pid_invalid";
        return result;
      }
      request.controller_pid = static_cast<std::int32_t>(number);
    } else {
      result.error = "command_invalid";
      return result;
    }
    if (request.command != Command::enable &&
        (root[@"config"] != nil || root[@"controllerPid"] != nil)) {
      result.error = "request_shape_invalid";
      return result;
    }
    result.request = std::move(request);
    return result;
  }
}

std::string encode_response_json(const std::string& request_id, bool ok,
                                 const RuntimeStatus& status) {
  @autoreleasepool {
    return serialize(@{
      @"protocolVersion" : @1,
      @"requestId" : [NSString stringWithUTF8String:request_id.c_str()],
      @"ok" : @(ok),
      @"status" : status_dictionary(status),
    });
  }
}

std::string encode_status_json(const RuntimeStatus& status) {
  @autoreleasepool {
    return serialize(status_dictionary(status));
  }
}

}  // namespace keydous::fn
