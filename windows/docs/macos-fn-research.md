# Integrated macOS Fn/remapping research

Research date: 2026-09-06. This is an implementation boundary and acceptance guide, not a claim that a Mac build or Keydous Fn hardware has been tested.

## Recommended application boundary

Keep remapping settings, validation, enable/disable, runtime status and shutdown in the existing Keydous Codex application. A platform backend can run in-process or as an application-owned helper; users need no separate Karabiner settings application or Karabiner profile. Keep lighting/screen transport independent: a working macOS remapper does not establish compatibility with the Windows Keydous IoT service.

Start with a native Quartz event-tap backend for ordinary keys and **OS-visible Fn input/chords**. It is a limited backend, not full Apple Fn/Globe emulation. Preserve source/target key identity, modifiers, down/up/repeat and active output ownership in an OS-independent model. Backend capabilities must distinguish Fn input, Fn output, consumer/media output, device filtering and runtime availability. A configuration can be saved without claiming unsupported rules are active.

The Windows backend should translate supported keys into Windows events independently of the Apple encoding. Do not invent a Windows Fn virtual key. Do not promise per-device rules when the backend only has global keyboard events. Firmware remapping and an OS remapper are different owners; no firmware writes are implied by saving OS rules.

## What Karabiner actually does

Source examined: `research/Karabiner-Elements`, commit `c1dab5d576267abb5eee66a797928b1843d85b11`; submodules were not initialized. Links below are pinned to that commit.

- Both Apple vendor-keyboard `function` and Apple vendor-top-case `keyboard_fn` normalize to one logical Fn modifier. `fn` is represented using the top-case usage; it is not an ordinary USB keyboard-page modifier. [momentary_switch_event.hpp](https://github.com/pqrs-org/Karabiner-Elements/blob/c1dab5d576267abb5eee66a797928b1843d85b11/src/share/types/momentary_switch_event.hpp#L78), [key_code.hpp](https://github.com/pqrs-org/Karabiner-Elements/blob/c1dab5d576267abb5eee66a797928b1843d85b11/src/share/types/momentary_switch_event_details/key_code.hpp#L232).
- The Quartz path recognizes Fn modifier changes using `kCGEventFlagsChanged` and `kCGEventFlagMaskSecondaryFn`. It also handles key-down, key-up and system-defined media events. [event_tap_utility.hpp](https://github.com/pqrs-org/Karabiner-Elements/blob/c1dab5d576267abb5eee66a797928b1843d85b11/src/share/event_tap_utility.hpp#L54).
- `fn_function_keys` is a function-row transformation stage. With standard function keys enabled, Fn+F1 maps to a media action; with the setting disabled, bare F1 maps to media and Fn+F1 yields F1. The stage accounts for later Apple keyboard-driver interpretation and accidental Fn tap side effects. Do not copy its virtual-HID output flags verbatim into a later Quartz interception layer. [fn_function_keys_manipulator_manager.hpp](https://github.com/pqrs-org/Karabiner-Elements/blob/c1dab5d576267abb5eee66a797928b1843d85b11/src/apps/CoreService/include/core_service/daemon/device_grabber_details/fn_function_keys_manipulator_manager.hpp#L21), [official function-key explanation](https://karabiner-elements.pqrs.org/docs/help/how-to/function-keys/).
- Quartz can already contain Fn-transformed navigation keys. Karabiner normalizes those and remembers the key-down interpretation for key-up even after Fn is released. A remapper must retain matched outputs through release; reevaluating key-up against current modifiers causes stuck or mismatched keys. [event_tap_monitor.hpp](https://github.com/pqrs-org/Karabiner-Elements/blob/c1dab5d576267abb5eee66a797928b1843d85b11/src/share/monitor/event_tap_monitor.hpp#L211).

A physical Keydous Fn key might be a firmware-only layer selector and emit no independent OS event. No software hook or Karabiner rule can infer that missing event reliably. Verify the target model, wired/wireless mode and Mac/Windows hardware mode before claiming physical Fn capture; mapping an observable ordinary key to an application-owned Fn layer is a separate supported behavior.

## Quartz limitations and permissions

Karabiner's development notes explicitly document that Quartz capture cannot identify the originating keyboard, misses events during Secure Event Input, and observes Caps Lock's toggled state rather than physical down/up edges. They also document that **Fn synthesized with CGEventPost does not trigger the configured standalone Globe action or Fn+Control+arrow window actions**. These are reasons Karabiner uses seized HID input and virtual HID output. [DEVELOPMENT.md](https://github.com/pqrs-org/Karabiner-Elements/blob/c1dab5d576267abb5eee66a797928b1843d85b11/DEVELOPMENT.md#L143).

For the limited backend, use a user-session active event tap, bounded callbacks and explicit lifecycle ownership. Preserve unmapped flags, avoid processing self-generated output, and release tracked outputs on stop/reconfiguration/permission loss or Secure Event Input transitions. Recover disabled taps without claiming interception remains active. Do not normalize Caps Lock as a regular physical key without a deliberate toggle policy.

Accessibility approval belongs to the actual native process performing remapping, not its browser settings tab. Check trust and tap creation results. If using listening/HID APIs, expose their Input Monitoring status separately; do not equate a successful Accessibility check with every input permission being granted. Prompt only through the application's explicit enable/setup action. [Apple Accessibility trust API](https://developer.apple.com/documentation/applicationservices/1459186-axisprocesstrustedwithoptions), [Apple input-listening preflight](https://developer.apple.com/documentation/coregraphics/cgpreflightlisteneventaccess()).

## Full Fn/Globe parity route

An integrated HID capture plus virtual-HID backend is credible but larger. Karabiner's pinned DriverKit dependency is `bdfcb459b2eaca8ccda680a73b0dc898f330f4bb`. Its current upstream guide describes a root client/daemon, driver activation, and an extension manager. A self-signed distribution requires Apple-approved DriverKit/HID entitlements, appropriate provisioning profiles, application/installer signing and notarization. System-extension and background-component setup must remain application-owned. Reusing the signed upstream driver still introduces installed privileged components; it does not reduce to a Python dependency. [DriverKit upstream build and architecture guide](https://github.com/pqrs-org/Karabiner-DriverKit-VirtualHIDDevice/blob/main/README.md).

Karabiner's top-level license is the Unlicense; dependency notices still require independent review before bundling. The present Keydous port retains its existing GPL-3.0-only obligations. No Karabiner binary or driver was bundled by this research. [Karabiner LICENSE.md](https://github.com/pqrs-org/Karabiner-Elements/blob/c1dab5d576267abb5eee66a797928b1843d85b11/LICENSE.md). Stable signing identity matters to persisted macOS permissions. [Karabiner build README](https://github.com/pqrs-org/Karabiner-Elements/blob/c1dab5d576267abb5eee66a797928b1843d85b11/README.md).

## Required Mac acceptance

Windows unit tests can verify rule validation, capability rejection, Fn normalization, held-key ownership, repeats, release ordering and shutdown reconciliation using simulated events. They cannot validate Quartz delivery, permissions, Globe behavior, media output or signed packaging.

On a real Mac, test permission denied/granted/revoked, both function-row preferences, observable Fn alone/chords, Fn released before the mapped key, left/right modifiers, Caps Lock, repeat, simultaneous mapped keys, mouse modifier flags, sleep/wake, keyboard disconnect and Secure Event Input transitions. Check ordinary application shortcuts and system actions separately. Test actual Keydous and Apple keyboards separately. Only advertise the behaviors that pass; a saved profile or importable Python module is not Mac hardware acceptance.
