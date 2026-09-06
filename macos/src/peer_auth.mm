#import <Foundation/Foundation.h>

#include "keydous_fn/peer_auth.hpp"

#include <Security/Security.h>
#include <SystemConfiguration/SystemConfiguration.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

namespace keydous::fn {
namespace {

bool signing_value(SecCodeRef code, CFStringRef key, NSString** output) {
  CFDictionaryRef information = nullptr;
  if (SecCodeCopySigningInformation(code, kSecCSSigningInformation, &information) !=
          errSecSuccess ||
      !information) {
    return false;
  }
  NSDictionary* values = CFBridgingRelease(information);
  id value = values[(__bridge NSString*)key];
  if (![value isKindOfClass:NSString.class] || [(NSString*)value length] == 0) return false;
  *output = value;
  return true;
}

bool valid_code(SecCodeRef code) {
  return code && SecCodeCheckValidity(code, kSecCSStrictValidate, nullptr) == errSecSuccess;
}

}  // namespace

std::uint32_t current_console_uid() {
  uid_t uid = static_cast<uid_t>(-1);
  gid_t gid = static_cast<gid_t>(-1);
  CFStringRef user = SCDynamicStoreCopyConsoleUser(nullptr, &uid, &gid);
  if (user) CFRelease(user);
  return uid == static_cast<uid_t>(-1) ? UINT32_MAX : static_cast<std::uint32_t>(uid);
}

bool authenticate_control_peer(int socket, AuthenticatedPeer& peer, std::string& error) {
  uid_t uid = 0;
  gid_t gid = 0;
  if (getpeereid(socket, &uid, &gid) != 0) {
    error = "peer_credentials_unavailable";
    return false;
  }
  const auto console_uid = current_console_uid();
  if (console_uid == UINT32_MAX || uid != console_uid || uid == 0) {
    error = "peer_not_console_user";
    return false;
  }

  pid_t pid = 0;
  socklen_t pid_length = sizeof(pid);
  if (getsockopt(socket, SOL_LOCAL, LOCAL_PEERPID, &pid, &pid_length) != 0 || pid <= 1) {
    error = "peer_pid_unavailable";
    return false;
  }

  @autoreleasepool {
    NSDictionary* attributes = @{(__bridge NSString*)kSecGuestAttributePid : @(pid)};
    SecCodeRef guest = nullptr;
    SecCodeRef self_code = nullptr;
    if (SecCodeCopyGuestWithAttributes(nullptr, (__bridge CFDictionaryRef)attributes,
                                       kSecCSDefaultFlags, &guest) != errSecSuccess ||
        SecCodeCopySelf(kSecCSDefaultFlags, &self_code) != errSecSuccess ||
        !valid_code(guest) || !valid_code(self_code)) {
      if (guest) CFRelease(guest);
      if (self_code) CFRelease(self_code);
      error = "peer_signature_invalid";
      return false;
    }

    NSString* guest_team = nil;
    NSString* helper_team = nil;
    NSString* guest_identifier = nil;
    const bool valid = signing_value(guest, kSecCodeInfoTeamIdentifier, &guest_team) &&
                       signing_value(self_code, kSecCodeInfoTeamIdentifier, &helper_team) &&
                       signing_value(guest, kSecCodeInfoIdentifier, &guest_identifier) &&
                       [guest_team isEqualToString:helper_team] &&
                       [guest_identifier isEqualToString:@"com.keydous.codex.fncontrol"];
    CFRelease(guest);
    CFRelease(self_code);
    if (!valid) {
      error = "peer_signing_identity_mismatch";
      return false;
    }
  }

  peer = {.uid = static_cast<std::uint32_t>(uid), .pid = pid};
  return true;
}

}  // namespace keydous::fn
