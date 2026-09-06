#include "keydous_fn/hid_capture.hpp"

#include "keydous_fn/device_discovery.hpp"

#include <IOKit/hid/IOHIDKeys.h>
#include <IOKit/hid/IOHIDManager.h>

#include <utility>

namespace keydous::fn {
namespace {

void value_callback(void* context, IOReturn result, void*, IOHIDValueRef value) {
  auto* capture = static_cast<HIDCapture*>(context);
  if (result != kIOReturnSuccess || !value) {
    capture->on_io_error();
    return;
  }
  const auto element = IOHIDValueGetElement(value);
  if (!element) return;
  const auto type = IOHIDElementGetType(element);
  if (type != kIOHIDElementTypeInput_Misc && type != kIOHIDElementTypeInput_Button &&
      type != kIOHIDElementTypeInput_ScanCodes) {
    return;
  }
  const auto page = IOHIDElementGetUsagePage(element);
  const auto usage = IOHIDElementGetUsage(element);
  if (page != keyboard_page && page != consumer_page &&
      page != generic_desktop_page &&
      page != apple_vendor_top_case_page && page != apple_vendor_keyboard_page) {
    return;
  }
  // Raw HID holds a key until its up edge; the virtual keyboard owns OS repeat.
  capture->on_value({page, usage}, IOHIDValueGetIntegerValue(value) != 0);
}

void removal_callback(void* context, IOReturn, void*) {
  auto* capture = static_cast<HIDCapture*>(context);
  capture->on_removed();
}

bool interface_is_fully_forwardable(IOHIDDeviceRef device) {
  CFArrayRef elements = IOHIDDeviceCopyMatchingElements(device, nullptr,
                                                        kIOHIDOptionsTypeNone);
  if (!elements) return false;
  bool result = true;
  const auto count = CFArrayGetCount(elements);
  for (CFIndex index = 0; index < count; ++index) {
    auto element = (IOHIDElementRef)CFArrayGetValueAtIndex(elements, index);
    const auto type = IOHIDElementGetType(element);
    if (type != kIOHIDElementTypeInput_Misc &&
        type != kIOHIDElementTypeInput_Button &&
        type != kIOHIDElementTypeInput_ScanCodes) {
      continue;
    }
    const auto page = IOHIDElementGetUsagePage(element);
    if (page == generic_desktop_page && type == kIOHIDElementTypeInput_Misc) {
      result = false;  // Axes cannot be represented by the keyboard's held-key report.
      break;
    }
    if (page != keyboard_page && page != consumer_page &&
        page != generic_desktop_page && page != apple_vendor_top_case_page &&
        page != apple_vendor_keyboard_page) {
      result = false;
      break;
    }
  }
  CFRelease(elements);
  return result;
}

}  // namespace

bool input_monitoring_denied() {
  return IOHIDCheckAccess(kIOHIDRequestTypeListenEvent) == kIOHIDAccessTypeDenied;
}

HIDCapture::HIDCapture(DeviceSelection selection, EventCallback callback)
    : selection_(std::move(selection)), callback_(std::move(callback)) {}

HIDCapture::~HIDCapture() { stop(); }

bool HIDCapture::start(std::string& error) {
  if (!callback_) {
    error = "input_callback_missing";
    return false;
  }
  if (input_monitoring_denied()) {
    error = "input_permission_required";
    return false;
  }
  thread_ = std::thread([this] { run(); });
  std::unique_lock lock(mutex_);
  condition_.wait(lock, [this] { return start_complete_; });
  error = start_error_;
  return error.empty() && captured_.load();
}

void HIDCapture::stop() {
  stop_requested_.store(true);
  CFRunLoopRef loop = nullptr;
  {
    std::lock_guard lock(mutex_);
    if (run_loop_) {
      loop = static_cast<CFRunLoopRef>(run_loop_);
      CFRetain(loop);
    }
  }
  if (loop) {
    CFRunLoopStop(loop);
    CFRelease(loop);
  }
  if (thread_.joinable() && thread_.get_id() != std::this_thread::get_id()) thread_.join();
}

std::string HIDCapture::take_failure() {
  std::lock_guard lock(mutex_);
  return std::exchange(failure_, {});
}

void HIDCapture::on_value(Usage usage, bool down) {
  if (!stop_requested_.load()) callback_(usage, down);
}

void HIDCapture::on_removed() {
  CFRunLoopRef loop = nullptr;
  {
    std::lock_guard lock(mutex_);
    failure_ = "device_disconnected";
    if (run_loop_) {
      loop = static_cast<CFRunLoopRef>(run_loop_);
      CFRetain(loop);
    }
  }
  if (loop) {
    CFRunLoopStop(loop);
    CFRelease(loop);
  }
}

void HIDCapture::on_io_error() {
  CFRunLoopRef loop = nullptr;
  {
    std::lock_guard lock(mutex_);
    failure_ = "input_stream_error";
    if (run_loop_) {
      loop = static_cast<CFRunLoopRef>(run_loop_);
      CFRetain(loop);
    }
  }
  if (loop) {
    CFRunLoopStop(loop);
    CFRelease(loop);
  }
}

void HIDCapture::run() {
  std::string error;
  IOHIDDeviceRef device = copy_selected_device(selection_, error);
  if (!device) {
    std::lock_guard lock(mutex_);
    start_error_ = std::move(error);
    start_complete_ = true;
    condition_.notify_all();
    return;
  }
  if (!interface_is_fully_forwardable(device)) {
    CFRelease(device);
    std::lock_guard lock(mutex_);
    start_error_ = "unsupported_input_interface";
    start_complete_ = true;
    condition_.notify_all();
    return;
  }

  const auto loop = CFRunLoopGetCurrent();
  {
    std::lock_guard lock(mutex_);
    run_loop_ = loop;
  }
  IOHIDDeviceRegisterInputValueCallback(device, value_callback, this);
  IOHIDDeviceRegisterRemovalCallback(device, removal_callback, this);
  IOHIDDeviceScheduleWithRunLoop(device, loop, kCFRunLoopDefaultMode);
  const auto opened = IOHIDDeviceOpen(device, kIOHIDOptionsTypeSeizeDevice);
  {
    std::lock_guard lock(mutex_);
    if (opened == kIOReturnSuccess) {
      captured_.store(true);
    } else if (opened == kIOReturnExclusiveAccess) {
      start_error_ = "input_conflict";
    } else {
      start_error_ = opened == kIOReturnNotPermitted ? "input_permission_required"
                                                      : "input_seize_failed";
    }
    start_complete_ = true;
  }
  condition_.notify_all();

  if (opened == kIOReturnSuccess && !stop_requested_.load()) CFRunLoopRun();

  if (opened == kIOReturnSuccess) IOHIDDeviceClose(device, kIOHIDOptionsTypeNone);
  IOHIDDeviceUnscheduleFromRunLoop(device, loop, kCFRunLoopDefaultMode);
  captured_.store(false);
  {
    std::lock_guard lock(mutex_);
    run_loop_ = nullptr;
  }
  CFRelease(device);
}

}  // namespace keydous::fn
