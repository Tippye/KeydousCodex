#import <AppKit/AppKit.h>
#import <CommonCrypto/CommonDigest.h>
#import <Foundation/Foundation.h>
#import <ServiceManagement/ServiceManagement.h>

#include "keydous_fn/device_discovery.hpp"
#include "keydous_fn/models.hpp"

#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>
#include <fcntl.h>

#include <array>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>

namespace {

static NSString* const helper_plist = @"com.keydous.codex.fnhelper.plist";
static NSString* const upstream_plist =
    @"org.pqrs.service.daemon.Karabiner-VirtualHIDDevice-Daemon.plist";
static NSString* const upstream_manager =
    @"/Applications/.Karabiner-VirtualHIDDevice-Manager.app/Contents/MacOS/Karabiner-VirtualHIDDevice-Manager";
static NSString* const upstream_daemon =
    @"/Library/Application Support/org.pqrs/Karabiner-DriverKit-VirtualHIDDevice/Applications/Karabiner-VirtualHIDDevice-Daemon.app/Contents/MacOS/Karabiner-VirtualHIDDevice-Daemon";
static NSString* const package_name = @"Karabiner-DriverKit-VirtualHIDDevice-8.5.0.pkg";
constexpr const char* package_sha256 =
    "d73d6d9428f0f80b87b8a8ba8a1031f2cbc3bc1fa6b74842d1f1b764b2916fc9";

enum class Action { status, enable, disable, remove_helper };

void print_json(NSDictionary* value) {
  NSData* data = [NSJSONSerialization dataWithJSONObject:value options:0 error:nil];
  if (data) {
    fwrite(data.bytes, 1, data.length, stdout);
    fputc('\n', stdout);
  }
}

NSMutableDictionary* local_status(NSString* state, NSString* message,
                                  NSString* error_code = nil) {
  std::string discovery_error;
  auto runtime = keydous::fn::RuntimeStatus{};
  runtime.state = state.UTF8String;
  runtime.message = message.UTF8String;
  runtime.candidates = keydous::fn::enumerate_candidates(discovery_error);
  if (error_code) runtime.error_code = error_code.UTF8String;
  const auto encoded = keydous::fn::encode_status_json(runtime);
  NSData* data = [NSData dataWithBytes:encoded.data() length:encoded.size()];
  NSMutableDictionary* result =
      [[NSJSONSerialization JSONObjectWithData:data options:NSJSONReadingMutableContainers
                                         error:nil] mutableCopy];
  return result ?: [NSMutableDictionary dictionary];
}

bool upstream_installed() {
  NSFileManager* files = NSFileManager.defaultManager;
  return [files isExecutableFileAtPath:upstream_manager] &&
         [files isExecutableFileAtPath:upstream_daemon];
}

bool upstream_version_matches() {
  NSBundle* bundle = [NSBundle bundleWithPath:
      @"/Applications/.Karabiner-VirtualHIDDevice-Manager.app"];
  NSString* version = [bundle objectForInfoDictionaryKey:@"CFBundleShortVersionString"];
  return [version isEqualToString:@"8.5.0"];
}

NSString* service_status_name(SMAppServiceStatus status) {
  switch (status) {
    case SMAppServiceStatusNotRegistered: return @"not_registered";
    case SMAppServiceStatusEnabled: return @"enabled";
    case SMAppServiceStatusRequiresApproval: return @"requires_approval";
    case SMAppServiceStatusNotFound: return @"not_found";
  }
  return @"unknown";
}

void overlay_service(NSMutableDictionary* status, SMAppService* helper,
                     SMAppService* upstream) {
  status[@"helperServiceStatus"] = service_status_name(helper.status);
  status[@"upstreamDaemonServiceStatus"] = service_status_name(upstream.status);
  const bool helper_registered = helper.status == SMAppServiceStatusEnabled ||
                                 helper.status == SMAppServiceStatusRequiresApproval;
  status[@"upstreamPackageInstalled"] = @(upstream_installed());
  status[@"installed"] = @(upstream_installed() && helper_registered);
  const bool runtime_requires_approval = [status[@"requiresApproval"] boolValue];
  status[@"requiresApproval"] =
      @(runtime_requires_approval ||
        helper.status == SMAppServiceStatusRequiresApproval ||
        upstream.status == SMAppServiceStatusRequiresApproval);
}

bool register_service(SMAppService* service, NSError** error) {
  if (service.status == SMAppServiceStatusEnabled) return true;
  if (service.status == SMAppServiceStatusNotFound) {
    NSError* ignored = nil;
    (void)[service unregisterAndReturnError:&ignored];
  }
  if (![service registerAndReturnError:error]) return false;
  return service.status == SMAppServiceStatusEnabled;
}

bool run_upstream_activation() {
  if (!upstream_installed()) return false;
  NSTask* task = [[NSTask alloc] init];
  task.executableURL = [NSURL fileURLWithPath:upstream_manager];
  task.arguments = @[@"activate"];
  task.standardOutput = NSFileHandle.fileHandleWithNullDevice;
  task.standardError = NSFileHandle.fileHandleWithNullDevice;
  NSError* error = nil;
  if (![task launchAndReturnError:&error]) return false;
  [task waitUntilExit];
  return task.terminationStatus == 0;
}

NSString* bundled_package_path() {
  return [NSBundle.mainBundle.resourcePath stringByAppendingPathComponent:
      [@"Driver" stringByAppendingPathComponent:package_name]];
}

bool verify_package_hash(NSString* path) {
  NSFileHandle* file = [NSFileHandle fileHandleForReadingAtPath:path];
  if (!file) return false;
  CC_SHA256_CTX context;
  CC_SHA256_Init(&context);
  while (true) {
    NSData* data = [file readDataOfLength:1024 * 1024];
    if (data.length == 0) break;
    CC_SHA256_Update(&context, data.bytes, static_cast<CC_LONG>(data.length));
  }
  [file closeFile];
  std::array<unsigned char, CC_SHA256_DIGEST_LENGTH> digest{};
  CC_SHA256_Final(digest.data(), &context);
  char encoded[CC_SHA256_DIGEST_LENGTH * 2 + 1]{};
  for (std::size_t i = 0; i < digest.size(); ++i)
    snprintf(encoded + i * 2, 3, "%02x", digest[i]);
  return strcmp(encoded, package_sha256) == 0;
}

bool run_assessment(NSString* executable, NSArray<NSString*>* arguments) {
  NSTask* task = [[NSTask alloc] init];
  task.executableURL = [NSURL fileURLWithPath:executable];
  task.arguments = arguments;
  task.standardOutput = NSFileHandle.fileHandleWithNullDevice;
  task.standardError = NSFileHandle.fileHandleWithNullDevice;
  NSError* error = nil;
  if (![task launchAndReturnError:&error]) return false;
  [task waitUntilExit];
  return task.terminationStatus == 0;
}

bool verify_package_signature(NSString* path) {
  return run_assessment(@"/usr/sbin/pkgutil", @[@"--check-signature", path]) &&
         run_assessment(@"/usr/sbin/spctl",
                        @[@"--assess", @"--type", @"install", @"--verbose=2", path]);
}

bool open_verified_installer() {
  NSString* path = bundled_package_path();
  if (!verify_package_hash(path) || !verify_package_signature(path)) return false;
  return [NSWorkspace.sharedWorkspace openURL:[NSURL fileURLWithPath:path]];
}

NSDictionary* config_dictionary(const std::string& json) {
  NSData* data = [NSData dataWithBytes:json.data() length:json.size()];
  id value = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
  return [value isKindOfClass:NSDictionary.class] ? value : nil;
}

bool read_config_file(NSString* path, std::string& output) {
  const int file = open(path.fileSystemRepresentation,
                        O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
  if (file < 0) return false;
  struct stat metadata {};
  if (fstat(file, &metadata) != 0 || !S_ISREG(metadata.st_mode) ||
      metadata.st_size <= 0 || metadata.st_size > 64 * 1024) {
    close(file);
    return false;
  }
  output.resize(static_cast<std::size_t>(metadata.st_size));
  std::size_t offset = 0;
  while (offset < output.size()) {
    const auto count = read(file, output.data() + offset, output.size() - offset);
    if (count <= 0) {
      close(file);
      output.clear();
      return false;
    }
    offset += static_cast<std::size_t>(count);
  }
  close(file);
  return true;
}

NSMutableDictionary* call_helper(NSDictionary* request, bool retry) {
  NSData* data = [NSJSONSerialization dataWithJSONObject:request options:0 error:nil];
  if (!data) return nil;
  NSMutableData* frame = [data mutableCopy];
  const char newline = '\n';
  [frame appendBytes:&newline length:1];

  const int attempts = retry ? 32 : 1;
  for (int attempt = 0; attempt < attempts; ++attempt) {
    const int connection = socket(AF_UNIX, SOCK_STREAM, 0);
    if (connection < 0) return nil;
    timeval timeout{.tv_sec = 15, .tv_usec = 0};
    setsockopt(connection, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(connection, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    sockaddr_un address{};
    address.sun_family = AF_UNIX;
    strlcpy(address.sun_path, keydous::fn::helper_socket_path, sizeof(address.sun_path));
    if (connect(connection, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0) {
      const auto sent = send(connection, frame.bytes, frame.length, MSG_NOSIGNAL);
      if (sent == static_cast<ssize_t>(frame.length)) {
        NSMutableData* response = [NSMutableData data];
        char buffer[4096];
        while (response.length <= 64 * 1024) {
          const auto count = recv(connection, buffer, sizeof(buffer), 0);
          if (count <= 0) break;
          const auto newline_at = static_cast<const char*>(memchr(buffer, '\n', count));
          const auto bytes = newline_at ? static_cast<NSUInteger>(newline_at - buffer)
                                        : static_cast<NSUInteger>(count);
          if (response.length + bytes > 64 * 1024) break;
          [response appendBytes:buffer
                        length:bytes];
          if (newline_at) break;
        }
        close(connection);
        id value = [NSJSONSerialization JSONObjectWithData:response
                                                   options:NSJSONReadingMutableContainers
                                                     error:nil];
        return [value isKindOfClass:NSDictionary.class] ? value : nil;
      }
    }
    close(connection);
    if (attempt + 1 < attempts) std::this_thread::sleep_for(std::chrono::milliseconds(250));
  }
  return nil;
}

int emit_helper_response(NSMutableDictionary* response, SMAppService* helper,
                         SMAppService* upstream, bool status_command) {
  NSMutableDictionary* status = [response[@"status"] mutableCopy];
  if (!status) status = local_status(@"error", @"The helper response was invalid.",
                                     @"helper_response_invalid");
  overlay_service(status, helper, upstream);
  print_json(status);
  return status_command || [response[@"ok"] boolValue] ? 0 : 1;
}

}  // namespace

int main(int argc, const char* argv[]) {
  @autoreleasepool {
    if (argc < 2 || argc > 5) {
      fprintf(stderr, "usage: keydous-macos-fn status|enable|disable|remove-helper [--config PATH] [--json]\n");
      return 64;
    }
    NSString* command = @(argv[1]);
    Action action;
    if ([command isEqualToString:@"status"]) action = Action::status;
    else if ([command isEqualToString:@"enable"]) action = Action::enable;
    else if ([command isEqualToString:@"disable"]) action = Action::disable;
    else if ([command isEqualToString:@"remove-helper"]) action = Action::remove_helper;
    else return 64;

    NSString* config_path = nil;
    for (int i = 2; i < argc; ++i) {
      NSString* argument = @(argv[i]);
      if ([argument isEqualToString:@"--json"]) continue;
      if ([argument isEqualToString:@"--config"] && i + 1 < argc) {
        config_path = @(argv[++i]);
        continue;
      }
      return 64;
    }
    if ((action == Action::enable) != (config_path != nil)) return 64;
    if (config_path && !config_path.isAbsolutePath) return 64;

    SMAppService* helper = [SMAppService daemonServiceWithPlistName:helper_plist];
    SMAppService* upstream = [SMAppService daemonServiceWithPlistName:upstream_plist];

    if (action == Action::remove_helper) {
      if (helper.status == SMAppServiceStatusEnabled) {
        NSString* request_id = NSUUID.UUID.UUIDString;
        auto response = call_helper(@{
          @"protocolVersion" : @1,
          @"requestId" : request_id,
          @"command" : @"disable",
        }, false);
        if (!response || ![response[@"ok"] boolValue]) {
          auto status = local_status(@"error",
                                     @"The helper did not acknowledge shutdown.",
                                     @"helper_shutdown_unacknowledged");
          overlay_service(status, helper, upstream);
          print_json(status);
          return 1;
        }
      }
      NSError* removal_error = nil;
      if (helper.status != SMAppServiceStatusNotRegistered &&
          helper.status != SMAppServiceStatusNotFound &&
          ![helper unregisterAndReturnError:&removal_error]) {
        auto status = local_status(@"error", @"The Keydous helper could not be unregistered.",
                                   @"helper_unregister_failed");
        overlay_service(status, helper, upstream);
        print_json(status);
        return 1;
      }
      auto status = local_status(@"not_installed",
                                 @"The Keydous helper was removed. Shared VirtualHIDDevice components were left installed.",
                                 @"helper_not_registered");
      overlay_service(status, helper, upstream);
      status[@"installed"] = @NO;
      status[@"requiresApproval"] = @NO;
      print_json(status);
      return 0;
    }

    if (!upstream_installed() && action != Action::disable) {
      auto status = local_status(@"not_installed",
                                 @"The signed VirtualHIDDevice package is not installed.",
                                 @"driver_install_required");
      status[@"installed"] = @NO;
      status[@"requiresApproval"] = @(action == Action::enable);
      overlay_service(status, helper, upstream);
      if (action == Action::enable && !open_verified_installer()) {
        status[@"state"] = @"error";
        status[@"errorCode"] = @"bundled_driver_package_invalid";
        status[@"message"] = @"The bundled driver package failed hash or macOS signature assessment.";
      }
      print_json(status);
      return action == Action::status ? 0 : 1;
    }

    if (!upstream_version_matches() && action != Action::disable) {
      auto status = local_status(@"error",
                                 @"The installed VirtualHIDDevice version is not the audited 8.5.0 build.",
                                 @"driver_mismatch");
      overlay_service(status, helper, upstream);
      print_json(status);
      return action == Action::status ? 0 : 1;
    }

    if (action == Action::enable) {
      NSError* registration_error = nil;
      const bool upstream_ready = register_service(upstream, &registration_error);
      const bool helper_ready = register_service(helper, &registration_error);
      if (!upstream_ready || !helper_ready) {
        auto status = local_status(@"requires_approval",
                                   @"Approve the two Keydous background items in System Settings.",
                                   @"background_approval_required");
        overlay_service(status, helper, upstream);
        print_json(status);
        return 1;
      }
      (void)run_upstream_activation();
    } else if (helper.status == SMAppServiceStatusRequiresApproval ||
               upstream.status == SMAppServiceStatusRequiresApproval) {
      auto status = local_status(@"requires_approval",
                                 @"Background item approval is required.",
                                 @"background_approval_required");
      overlay_service(status, helper, upstream);
      print_json(status);
      return action == Action::status ? 0 : 1;
    } else if (helper.status != SMAppServiceStatusEnabled) {
      auto status = local_status(@"not_installed",
                                 @"The Keydous native Fn helper is not registered.",
                                 @"helper_not_registered");
      overlay_service(status, helper, upstream);
      print_json(status);
      return action == Action::status ? 0 : 1;
    }

    NSString* request_id = NSUUID.UUID.UUIDString;
    NSMutableDictionary* request = [@{
      @"protocolVersion" : @1,
      @"requestId" : request_id,
      @"command" : command,
    } mutableCopy];
    if (action == Action::enable) {
      std::string config_json;
      if (!read_config_file(config_path, config_json)) {
        auto status = local_status(@"error", @"The native Fn configuration could not be read.",
                                   @"config_read_failed");
        overlay_service(status, helper, upstream);
        print_json(status);
        return 1;
      }
      auto decoded = keydous::fn::decode_configuration_json(config_json);
      if (!decoded.configuration) {
        auto status = local_status(
            @"error", @"The native Fn configuration was rejected.",
            [NSString stringWithUTF8String:decoded.error.c_str()]);
        overlay_service(status, helper, upstream);
        print_json(status);
        return 1;
      }
      request[@"config"] = config_dictionary(config_json);
      request[@"controllerPid"] = @(getppid());
    }

    auto response = call_helper(request, action == Action::enable);
    if (!response || ![response[@"requestId"] isEqualToString:request_id] ||
        [response[@"protocolVersion"] integerValue] != 1) {
      auto status = local_status(@"error", @"The native Fn helper is unavailable.",
                                 @"daemon_unavailable");
      overlay_service(status, helper, upstream);
      print_json(status);
      return action == Action::status ? 0 : 1;
    }
    return emit_helper_response(response, helper, upstream, action == Action::status);
  }
}
