cmake_minimum_required(VERSION 3.24)
project(KeydousMacOSFn LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(keydous_fn_report_state STATIC src/report_state.cpp)
target_include_directories(keydous_fn_report_state PUBLIC include)
if(MSVC)
  target_compile_options(keydous_fn_report_state PRIVATE /W4)
else()
  target_compile_options(keydous_fn_report_state PRIVATE -Wall -Wextra -Wpedantic)
endif()

enable_testing()
add_executable(report_state_tests tests/report_state_tests.cpp)
target_link_libraries(report_state_tests PRIVATE keydous_fn_report_state)
add_test(NAME report_state_tests COMMAND report_state_tests)
add_executable(keyboard_teardown_state_tests tests/keyboard_teardown_state_tests.cpp)
target_include_directories(keyboard_teardown_state_tests PRIVATE include)
add_test(NAME keyboard_teardown_state_tests COMMAND keyboard_teardown_state_tests)

if(APPLE)
  enable_language(OBJCXX)
  set(CMAKE_OBJCXX_STANDARD 23)
  set(CMAKE_OBJCXX_STANDARD_REQUIRED ON)
  set(CMAKE_OBJCXX_EXTENSIONS OFF)
  set(CMAKE_OSX_DEPLOYMENT_TARGET "13.0" CACHE STRING "Minimum macOS version")
  set(KEYDOUS_VHID_SOURCE "" CACHE PATH "Pinned Karabiner VirtualHIDDevice source tree")
  if(NOT KEYDOUS_VHID_SOURCE)
    message(FATAL_ERROR "Set KEYDOUS_VHID_SOURCE to pinned VirtualHIDDevice source")
  endif()
  execute_process(
    COMMAND git -C "${KEYDOUS_VHID_SOURCE}" rev-parse HEAD
    OUTPUT_VARIABLE VHID_COMMIT OUTPUT_STRIP_TRAILING_WHITESPACE
    RESULT_VARIABLE VHID_GIT_RESULT)
  if(NOT VHID_GIT_RESULT EQUAL 0 OR
     NOT VHID_COMMIT STREQUAL "bdfcb459b2eaca8ccda680a73b0dc898f330f4bb")
    message(FATAL_ERROR "VirtualHIDDevice must be commit bdfcb459b2eaca8ccda680a73b0dc898f330f4bb")
  endif()
  file(READ "${KEYDOUS_VHID_SOURCE}/version.json" VHID_VERSION_JSON)
  string(JSON VHID_PACKAGE_VERSION GET "${VHID_VERSION_JSON}" package_version)
  string(JSON VHID_PROTOCOL_VERSION GET "${VHID_VERSION_JSON}" client_protocol_version)
  if(NOT VHID_PACKAGE_VERSION STREQUAL "8.5.0" OR NOT VHID_PROTOCOL_VERSION EQUAL 7)
    message(FATAL_ERROR "VirtualHIDDevice package/protocol version does not match the audited pin")
  endif()

  find_library(APPKIT_FRAMEWORK AppKit REQUIRED)
  find_library(COREFOUNDATION_FRAMEWORK CoreFoundation REQUIRED)
  find_library(FOUNDATION_FRAMEWORK Foundation REQUIRED)
  find_library(IOKIT_FRAMEWORK IOKit REQUIRED)
  find_library(SECURITY_FRAMEWORK Security REQUIRED)
  find_library(SERVICEMANAGEMENT_FRAMEWORK ServiceManagement REQUIRED)
  find_library(SYSTEMCONFIGURATION_FRAMEWORK SystemConfiguration REQUIRED)

  add_library(keydous_fn_common STATIC
    src/device_discovery.mm
    src/json_codec.mm)
  target_include_directories(keydous_fn_common PUBLIC include)
  target_compile_options(keydous_fn_common PRIVATE -fobjc-arc -Wall -Wextra -Wpedantic)
  target_link_libraries(keydous_fn_common PUBLIC
    ${FOUNDATION_FRAMEWORK} ${IOKIT_FRAMEWORK} ${COREFOUNDATION_FRAMEWORK})

  add_executable(keydous-macos-fn src/control_main.mm)
  set_target_properties(keydous-macos-fn PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/build")
  target_compile_options(keydous-macos-fn PRIVATE -fobjc-arc -Wall -Wextra -Wpedantic)
  target_link_libraries(keydous-macos-fn PRIVATE keydous_fn_common
    ${APPKIT_FRAMEWORK} ${SERVICEMANAGEMENT_FRAMEWORK})

  add_executable(keydous-fn-helper
    src/helper_main.mm
    src/hid_capture.mm
    src/ipc_server.mm
    src/peer_auth.mm
    src/process_identity.cpp
    src/runtime_controller.cpp
    src/virtual_hid_bridge.cpp)
  set_target_properties(keydous-fn-helper PROPERTIES
    OUTPUT_NAME "com.keydous.codex.fnhelper"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/build")
  target_include_directories(keydous-fn-helper PRIVATE
    include
    "${KEYDOUS_VHID_SOURCE}/include"
    "${KEYDOUS_VHID_SOURCE}/vendor/vendor/include")
  target_compile_options(keydous-fn-helper PRIVATE
    $<$<COMPILE_LANGUAGE:OBJCXX>:-fobjc-arc>
    -pthread -Wall -Wextra -Wpedantic)
  target_link_libraries(keydous-fn-helper PRIVATE
    keydous_fn_common keydous_fn_report_state
    ${SECURITY_FRAMEWORK} ${SYSTEMCONFIGURATION_FRAMEWORK})
endif()
