#pragma once

#include <cstdint>
#include <compare>
#include <functional>
#include <map>
#include <set>
#include <vector>

namespace keydous::fn {

inline constexpr std::uint32_t keyboard_page = 0x0007;
inline constexpr std::uint32_t consumer_page = 0x000c;
inline constexpr std::uint32_t generic_desktop_page = 0x0001;
inline constexpr std::uint32_t apple_vendor_top_case_page = 0x00ff;
inline constexpr std::uint32_t apple_vendor_keyboard_page = 0xff01;
inline constexpr std::uint32_t keyboard_fn_usage = 0x0003;

struct Usage final {
  std::uint32_t page{};
  std::uint32_t value{};

  auto operator<=>(const Usage&) const = default;
};

struct Mapping final {
  Usage source;
  Usage target;
};

struct Snapshot final {
  std::set<std::uint32_t> keyboard;
  std::set<std::uint32_t> consumer;
  std::set<std::uint32_t> generic_desktop;
  std::set<std::uint32_t> apple_vendor_top_case;
  std::set<std::uint32_t> apple_vendor_keyboard;

  [[nodiscard]] bool empty() const noexcept;
};

// Owns complete currently-held output reports. An input key retains the output
// selected on key-down until its matching key-up, even if mappings change.
class ReportState final {
 public:
  using Sink = std::function<void(const Snapshot&)>;

  explicit ReportState(Sink sink);

  void set_mappings(std::vector<Mapping> mappings);
  void handle(Usage input, bool down);
  void release_all();

  [[nodiscard]] const Snapshot& snapshot() const noexcept { return snapshot_; }
  [[nodiscard]] std::size_t held_input_count() const noexcept { return held_inputs_.size(); }

 private:
  [[nodiscard]] Usage output_for(Usage input) const;
  void retain(Usage output);
  void release(Usage output);
  void publish();

  Sink sink_;
  std::map<Usage, Usage> mappings_;
  std::map<Usage, Usage> held_inputs_;
  std::map<Usage, std::size_t> output_references_;
  Snapshot snapshot_;
};

}  // namespace keydous::fn
