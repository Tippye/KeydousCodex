#pragma once

#include "keydous_fn/models.hpp"

#include <IOKit/hid/IOHIDDevice.h>

#include <string>
#include <vector>

namespace keydous::fn {

std::vector<DeviceCandidate> enumerate_candidates(std::string& error);

// Returns a retained device reference. The caller owns one CFRelease.
IOHIDDeviceRef copy_selected_device(const DeviceSelection& selection,
                                    std::string& error);

}  // namespace keydous::fn
