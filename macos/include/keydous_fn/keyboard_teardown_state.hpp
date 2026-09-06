#pragma once

#include <cstdint>
#include <optional>

namespace keydous::fn {

// Separates ownership from readiness. A transport failure may make readiness
// false without proving that the daemon destroyed this client's keyboard.
class KeyboardTeardownState final {
 public:
  using Token = std::uint64_t;

  void mark_requested() noexcept { owned_ = true; }
  void observe_ready(bool value) noexcept {
    ready_ = value;
    ++revision_;
  }
  void observe_transport_loss() noexcept { ready_ = false; }

  [[nodiscard]] bool ready() const noexcept { return ready_; }
  [[nodiscard]] bool owned() const noexcept { return owned_; }
  [[nodiscard]] std::optional<Token> begin_termination() const noexcept {
    if (!owned_) return std::nullopt;
    return revision_;
  }
  [[nodiscard]] bool acknowledged(Token token) const noexcept {
    return revision_ > token && !ready_;
  }
  void complete_termination() noexcept {
    owned_ = false;
    ready_ = false;
  }

 private:
  bool owned_{};
  bool ready_{};
  Token revision_{};
};

}  // namespace keydous::fn
