#include "keydous_fn/keyboard_teardown_state.hpp"

#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>

using keydous::fn::KeyboardTeardownState;

namespace {
void require(bool condition, std::string_view message) {
  if (!condition) throw std::runtime_error(std::string(message));
}
}  // namespace

int main() {
  try {
    KeyboardTeardownState state;
    require(!state.begin_termination(), "unowned keyboard needs no teardown");

    state.mark_requested();
    state.observe_ready(true);
    const auto normal = state.begin_termination();
    require(normal.has_value(), "requested keyboard must be owned");
    state.observe_ready(false);
    require(state.acknowledged(*normal), "fresh false readiness acknowledges teardown");
    state.complete_termination();
    require(!state.owned(), "acknowledged teardown clears ownership");

    state.mark_requested();
    state.observe_ready(true);
    state.observe_transport_loss();
    const auto after_loss = state.begin_termination();
    require(after_loss.has_value(), "transport loss must retain ownership");
    require(!state.acknowledged(*after_loss),
            "local readiness loss is not a daemon teardown acknowledgement");
    state.observe_ready(false);
    require(state.acknowledged(*after_loss),
            "fresh daemon false readiness acknowledges teardown after loss");

    std::cout << "keyboard_teardown_state_tests: PASS\n";
    return EXIT_SUCCESS;
  } catch (const std::exception& error) {
    std::cerr << "keyboard_teardown_state_tests: FAIL: " << error.what() << '\n';
    return EXIT_FAILURE;
  }
}
