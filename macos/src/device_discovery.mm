#import <Foundation/Foundation.h>

#include "keydous_fn/device_discovery.hpp"

#include <IOKit/IOKitLib.h>
#include <IOKit/hid/IOHIDKeys.h>
#include <IOKit/hid/IOHIDManager.h>

#include <algorithm>

namespace keydous::fn {
namespace {

template <typename T>
class CFHandle final {
 public:
  explicit CFHandle(T value = nullptr) : value_(value) {}
  ~CFHandle() {
    if (value_) CFRelease(value_);
  }
  CFHandle(const CFHandle&) = delete;
  CFHandle& operator=(const CFHandle&) = delete;
  [[nodiscard]] T get() const { return value_; }

 private:
  T value_;
};

std::uint32_t number_property(IOHIDDeviceRef device, CFStringRef key) {
  const auto value = IOHIDDeviceGetProperty(device, key);
  if (!value || CFGetTypeID(value) != CFNumberGetTypeID()) return 0;
  std::int64_t number = 0;
  if (!CFNumberGetValue((CFNumberRef)value, kCFNumberSInt64Type, &number) ||
      number < 0 || number > UINT32_MAX) {
    return 0;
  }
  return static_cast<std::uint32_t>(number);
}

std::string string_property(IOHIDDeviceRef device, CFStringRef key) {
  const auto value = IOHIDDeviceGetProperty(device, key);
  if (!value || CFGetTypeID(value) != CFStringGetTypeID()) return {};
  NSString* string = (__bridge NSString*)(CFStringRef)value;
  return std::string(string.UTF8String ?: "");
}

std::uint64_t registry_id(IOHIDDeviceRef device) {
  const auto service = IOHIDDeviceGetService(device);
  std::uint64_t result = 0;
  if (service) (void)IORegistryEntryGetRegistryEntryID(service, &result);
  return result;
}

bool is_candidate(IOHIDDeviceRef device) {
  if (number_property(device, CFSTR(kIOHIDVendorIDKey)) != keydous_vendor_id ||
      number_property(device, CFSTR(kIOHIDProductIDKey)) != nj98_product_id) {
    return false;
  }
  const auto transport = string_property(device, CFSTR(kIOHIDTransportKey));
  if (transport != "USB") return false;
  const auto product = string_property(device, CFSTR(kIOHIDProductKey));
  if (product.find("Karabiner") != std::string::npos ||
      product.find("VirtualHID") != std::string::npos) {
    return false;
  }
  return registry_id(device) != 0;
}

NSDictionary* keyboard_match() {
  return @{
    @kIOHIDDeviceUsagePageKey : @(kHIDPage_GenericDesktop),
    @kIOHIDDeviceUsageKey : @(kHIDUsage_GD_Keyboard),
  };
}

std::vector<IOHIDDeviceRef> copy_keyboard_devices(std::string& error) {
  CFHandle<IOHIDManagerRef> manager(IOHIDManagerCreate(kCFAllocatorDefault,
                                                       kIOHIDOptionsTypeNone));
  if (!manager.get()) {
    error = "hid_manager_unavailable";
    return {};
  }
  IOHIDManagerSetDeviceMatching(manager.get(), (__bridge CFDictionaryRef)keyboard_match());
  const auto opened = IOHIDManagerOpen(manager.get(), kIOHIDOptionsTypeNone);
  if (opened != kIOReturnSuccess) {
    error = opened == kIOReturnNotPermitted ? "input_permission_required"
                                             : "hid_manager_open_failed";
    return {};
  }
  CFHandle<CFSetRef> devices(IOHIDManagerCopyDevices(manager.get()));
  std::vector<IOHIDDeviceRef> result;
  if (devices.get()) {
    const auto count = CFSetGetCount(devices.get());
    std::vector<const void*> values(static_cast<std::size_t>(count));
    CFSetGetValues(devices.get(), values.data());
    for (const auto value : values) {
      auto device = (IOHIDDeviceRef)value;
      if (is_candidate(device)) {
        CFRetain(device);
        result.push_back(device);
      }
    }
  }
  IOHIDManagerClose(manager.get(), kIOHIDOptionsTypeNone);
  return result;
}

DeviceCandidate candidate_from(IOHIDDeviceRef device) {
  return {
      .registry_entry_id = registry_id(device),
      .vendor_id = number_property(device, CFSTR(kIOHIDVendorIDKey)),
      .product_id = number_property(device, CFSTR(kIOHIDProductIDKey)),
      .product = string_property(device, CFSTR(kIOHIDProductKey)),
      .serial_number = string_property(device, CFSTR(kIOHIDSerialNumberKey)),
      .transport = string_property(device, CFSTR(kIOHIDTransportKey)),
  };
}

}  // namespace

std::vector<DeviceCandidate> enumerate_candidates(std::string& error) {
  auto devices = copy_keyboard_devices(error);
  std::vector<DeviceCandidate> result;
  for (const auto device : devices) {
    result.push_back(candidate_from(device));
    CFRelease(device);
  }
  std::ranges::sort(result, {}, &DeviceCandidate::registry_entry_id);
  return result;
}

IOHIDDeviceRef copy_selected_device(const DeviceSelection& selection,
                                    std::string& error) {
  if (selection.vendor_id != keydous_vendor_id ||
      selection.product_id != nj98_product_id || selection.transport != "USB" ||
      selection.registry_entry_id == 0) {
    error = "device_selection_invalid";
    return nullptr;
  }
  auto devices = copy_keyboard_devices(error);
  IOHIDDeviceRef selected = nullptr;
  for (const auto device : devices) {
    const auto candidate = candidate_from(device);
    if (candidate.registry_entry_id == selection.registry_entry_id &&
        candidate.vendor_id == selection.vendor_id &&
        candidate.product_id == selection.product_id &&
        candidate.transport == selection.transport) {
      if (selected) {
        error = "ambiguous_device";
        CFRelease(selected);
        selected = nullptr;
        break;
      }
      selected = device;
      CFRetain(selected);
    }
  }
  for (const auto device : devices) CFRelease(device);
  if (!selected && error.empty()) error = "device_not_found";
  return selected;
}

}  // namespace keydous::fn
