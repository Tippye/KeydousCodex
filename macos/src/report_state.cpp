#include "keydous_fn/report_state.hpp"

#include <stdexcept>
#include <utility>

namespace keydous::fn {

namespace {

std::set<std::uint32_t>& page_set(Snapshot& snapshot, std::uint32_t page) {
  switch (page) {
    case keyboard_page:
      return snapshot.keyboard;
    case consumer_page:
      return snapshot.consumer;
    case generic_desktop_page:
      return snapshot.generic_desktop;
    case apple_vendor_top_case_page:
      return snapshot.apple_vendor_top_case;
    case apple_vendor_keyboard_page:
      return snapshot.apple_vendor_keyboard;
    default:
      throw std::invalid_argument("unsupported output usage page");
  }
}

}  // namespace

bool Snapshot::empty() const noexcept {
  return keyboard.empty() && consumer.empty() && generic_desktop.empty() &&
         apple_vendor_top_case.empty() && apple_vendor_keyboard.empty();
}

ReportState::ReportState(Sink sink) : sink_(std::move(sink)) {
  if (!sink_) {
    throw std::invalid_argument("report sink is required");
  }
}

void ReportState::set_mappings(std::vector<Mapping> mappings) {
  std::map<Usage, Usage> replacement;
  for (const auto& mapping : mappings) {
    if (mapping.source.page == 0 || mapping.source.value == 0 ||
        mapping.target.page == 0 || mapping.target.value == 0) {
      throw std::invalid_argument("zero usage is not a valid mapping");
    }
    (void)page_set(snapshot_, mapping.target.page);
    if (!replacement.emplace(mapping.source, mapping.target).second) {
      throw std::invalid_argument("duplicate mapping source");
    }
  }
  mappings_ = std::move(replacement);
}

Usage ReportState::output_for(Usage input) const {
  if (const auto found = mappings_.find(input); found != mappings_.end()) {
    return found->second;
  }
  return input;
}

void ReportState::handle(Usage input, bool down) {
  if (input.page != keyboard_page && input.page != consumer_page &&
      input.page != generic_desktop_page &&
      input.page != apple_vendor_top_case_page &&
      input.page != apple_vendor_keyboard_page) {
    return;
  }

  if (down) {
    if (held_inputs_.contains(input)) {
      return;
    }
    const auto output = output_for(input);
    (void)page_set(snapshot_, output.page);
    held_inputs_.emplace(input, output);
    retain(output);
    publish();
    return;
  }

  const auto found = held_inputs_.find(input);
  if (found == held_inputs_.end()) {
    return;
  }
  const auto output = found->second;
  held_inputs_.erase(found);
  release(output);
  publish();
}

void ReportState::retain(Usage output) {
  auto& count = output_references_[output];
  ++count;
  if (count == 1) {
    page_set(snapshot_, output.page).insert(output.value);
  }
}

void ReportState::release(Usage output) {
  const auto found = output_references_.find(output);
  if (found == output_references_.end()) {
    return;
  }
  if (--found->second == 0) {
    page_set(snapshot_, output.page).erase(output.value);
    output_references_.erase(found);
  }
}

void ReportState::release_all() {
  if (held_inputs_.empty() && snapshot_.empty()) {
    return;
  }
  held_inputs_.clear();
  output_references_.clear();
  snapshot_ = {};
  publish();
}

void ReportState::publish() { sink_(snapshot_); }

}  // namespace keydous::fn
