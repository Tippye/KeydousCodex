#include "keydous_fn/report_state.hpp"

#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

using keydous::fn::Mapping;
using keydous::fn::ReportState;
using keydous::fn::Snapshot;
using keydous::fn::Usage;

namespace {

void require(bool condition, std::string_view message) {
  if (!condition) {
    throw std::runtime_error(std::string(message));
  }
}

void test_passthrough_and_release() {
  std::vector<Snapshot> reports;
  ReportState state([&](const auto& report) { reports.push_back(report); });
  state.handle({keydous::fn::keyboard_page, 4}, true);
  state.handle({keydous::fn::keyboard_page, 0xe1}, true);
  state.handle({keydous::fn::keyboard_page, 4}, false);
  require(reports.size() == 3, "every state change publishes once");
  require(reports.back().keyboard == std::set<std::uint32_t>{0xe1},
          "modifier remains held after ordinary key release");
}

void test_mapping_is_retained_until_key_up() {
  std::vector<Snapshot> reports;
  ReportState state([&](const auto& report) { reports.push_back(report); });
  state.set_mappings({{{keydous::fn::keyboard_page, 0xe4},
                       {keydous::fn::apple_vendor_top_case_page,
                        keydous::fn::keyboard_fn_usage}}});
  state.handle({keydous::fn::keyboard_page, 0xe4}, true);
  state.set_mappings({});
  state.handle({keydous::fn::keyboard_page, 0xe4}, false);
  require(reports.size() == 2, "configuration changes do not synthesize edges");
  require(reports.front().apple_vendor_top_case.contains(keydous::fn::keyboard_fn_usage),
          "mapped key presses native Fn");
  require(reports.back().empty(), "key-up releases the output chosen on key-down");
}

void test_shared_output_reference_count() {
  std::vector<Snapshot> reports;
  ReportState state([&](const auto& report) { reports.push_back(report); });
  const Usage fn{keydous::fn::apple_vendor_top_case_page,
                 keydous::fn::keyboard_fn_usage};
  state.set_mappings({{{keydous::fn::keyboard_page, 0xe0}, fn},
                      {{keydous::fn::keyboard_page, 0xe4}, fn}});
  state.handle({keydous::fn::keyboard_page, 0xe0}, true);
  state.handle({keydous::fn::keyboard_page, 0xe4}, true);
  state.handle({keydous::fn::keyboard_page, 0xe0}, false);
  require(reports.back().apple_vendor_top_case.contains(keydous::fn::keyboard_fn_usage),
          "one source cannot release another source's Fn output");
  state.handle({keydous::fn::keyboard_page, 0xe4}, false);
  require(reports.back().empty(), "last source releases shared output");
}

void test_repeat_is_ignored_and_stop_reconciles_all_pages() {
  std::vector<Snapshot> reports;
  ReportState state([&](const auto& report) { reports.push_back(report); });
  state.handle({keydous::fn::keyboard_page, 5}, true);
  state.handle({keydous::fn::keyboard_page, 5}, true);
  state.handle({keydous::fn::consumer_page, 0xe9}, true);
  state.handle({keydous::fn::generic_desktop_page, 0x81}, true);
  state.handle({keydous::fn::apple_vendor_keyboard_page, 3}, true);
  require(reports.size() == 4, "raw repeated downs do not duplicate ownership");
  state.release_all();
  require(reports.back().empty(), "stop publishes empty reports for every page");
  require(state.held_input_count() == 0, "stop clears retained input ownership");
}

}  // namespace

int main() {
  try {
    test_passthrough_and_release();
    test_mapping_is_retained_until_key_up();
    test_shared_output_reference_count();
    test_repeat_is_ignored_and_stop_reconciles_all_pages();
    std::cout << "report_state_tests: PASS\n";
    return EXIT_SUCCESS;
  } catch (const std::exception& error) {
    std::cerr << "report_state_tests: FAIL: " << error.what() << '\n';
    return EXIT_FAILURE;
  }
}
