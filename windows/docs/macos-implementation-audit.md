# Python/Web macOS integration implementation audit

Audited 2026-09-06 on Windows. No Mac executable was built or run; no driver was installed; no physical input or keyboard write was performed. This packet implements the approved same-application Windows/macOS direction. The repository's older Swift/NuPhy product contract is not evidence that this Python/Keydous product already supports macOS.

## Findings and next bounded slice

The existing Python/Web application can be made launchable on macOS without changing its screen/RGB protocol owner. Full Fn/Globe requires an internal native input component plus virtual HID output; a Quartz-only fallback cannot satisfy that requirement. Reusing the unmodified signed upstream VirtualHIDDevice package avoids building a new DriverKit extension, but still requires an installed extension, its signed daemon, and an application-owned root client. Keep the HTTP server, previews, Hooks and Python process unprivileged.

Implement the following in one Python portability slice, with platform-injected tests. These are necessary changes, not a claim that the resulting application or IoT connection is Mac-accepted.

| Owner | Current obstruction | Minimal change |
| --- | --- | --- |
| `instance.py:HardwareOwner` | Explicitly rejects every non-Windows host | Preserve Windows named mutex; on Darwin hold a nonblocking `fcntl.flock` on one stable per-user lock outside configurable `--data-dir`. Do not unlink the lock while releasing it. Ports and alternate data directories must share this owner. Existing `HookStore._lock` already demonstrates a POSIX implementation. |
| `config.py:data_directory` | Falls back to `~/KeydousCodex` | Use `~/Library/Application Support/KeydousCodex` on Darwin. Keep explicit `--data-dir` and Windows behavior. |
| `__main__.py` | Failure path can call `ctypes.windll` on Mac when stderr is absent | Put platform error display behind one function; Darwin may log/use native application UI. Ensure owner/server/app cleanup also happens on partial initialization and SIGTERM. |
| `integration.py:_source_command` | Always constructs encoded Windows PowerShell; frozen executable is `.exe` | Select the platform launcher before Hook materialization. On Darwin use a POSIX command built with `shlex.join([executable, *arguments])`; bind the actual frozen console Hook helper or source runner and imported modules in the existing integrity digest. Keep current Windows quoting unchanged. Emit `commandWindows` only for a Windows definition; keep platform-neutral review text and validate the actual command returned by `hooks/list`. A platform/runtime change must change reviewed digest. |
| `codex_rpc.py:find_codex` | Only discovers Windows desktop directories before PATH | Add Darwin candidates `/Applications/Codex.app/Contents/Resources/codex` and `~/Applications/Codex.app/Contents/Resources/codex`, with executable checks and bounded PATH fallback. These paths are already used by `app/Sources/KeyphoreApp/SystemGuidedSetup.swift`; do not inspect private desktop state or change RPC scope. |
| `pets.py:_find_codex_asar` | Refuses non-Windows, then queries Appx | Add the two normal Codex bundles with `Contents/Resources/app.asar`. Treat this as a checked candidate path, not a guaranteed bundle contract. Require an existing unique chosen installation; preserve all current ASAR/image validation. Expose unavailable import honestly. |
| `app.py` | Status omits platform/input readiness; lock telemetry deliberately returns unknown outside Windows | Expose independent platform, IoT and virtual-HID capability/status fields. `locks()` returning unknown is safe until native telemetry exists. Own start/stop of the native adapter through the current application lifecycle and serialized control boundary. |
| build/package scripts | Windows `.spec`, PowerShell and `.exe` assumptions | A separate Mac packaging entry point must assemble the same Python package and Web assets plus internal native components. Do not repurpose the older Swift NuPhy application as this port. |

The first follow-on native slice should deliver a C++23 adapter with a read-only `status`/enumeration path, verified report construction, explicit enable/disable and an authenticated IPC contract. It must default to no capture/output. Implement input selection, virtual keyboard readiness, held-output ownership and fail-open teardown before enabling real interception. A saved profile alone must never produce `active: true`.

## Pinned upstream dependency and reproducibility

Local inspected source: sibling `research/Karabiner-DriverKit-VirtualHIDDevice`, commit `bdfcb459b2eaca8ccda680a73b0dc898f330f4bb`, the exact gitlink of inspected Karabiner-Elements commit `c1dab5d576267abb5eee66a797928b1843d85b11`.

- `version.json`: package **8.5.0**, driver **1.8.0**, client protocol **7**.
- `dist/Karabiner-DriverKit-VirtualHIDDevice-8.5.0.pkg`, locally measured SHA-256: `d73d6d9428f0f80b87b8a8ba8a1031f2cbc3bc1fa6b74842d1f1b764b2916fc9`. Hash verification is not signature/notarization verification; those require Mac tooling.
- Client: `include/pqrs/karabiner/driverkit/virtual_hid_device_service/client.hpp`; reports: `include/pqrs/karabiner/driverkit/virtual_hid_device_driver/hid_report/`.
- Include paths: upstream `include` and `vendor/vendor/include`. The pinned tree already includes vendored headers. If regenerating them, use pinned `vendor/cpm-cmake-package-lock` gitlink `6a8b2d64b993746d489432b45455e33b7fb8e09f`, CMake >= 3.24 and `vendor/CMakeLists.txt`. Never run `make update` for a reproducible build.
- Upstream example `examples/virtual-hid-device-service-client/project.yml` uses C++23 and deployment target macOS 13.0. The full driver package build guide requires macOS 15+ and Xcode 16.3+, but reusing its package does not require compiling the extension.
- **Source correction:** `include/.../virtual_hid_device_service/constants.hpp` uses `/Library/Application Support/org.pqrs/tmp/rootonly/karabiner_virtual_hid_device_service.sock`. The README's `vhidd_server/*.sock` example is stale at this commit. Use the C++ client, not a Python recreation of its wire format.
- Top-level license is Unlicense; the client headers carry Boost Software License 1.0, and vendored dependencies have their own notices. Preserve those notices alongside this product's GPL-3.0-only notices.

[Pinned version](https://github.com/pqrs-org/Karabiner-DriverKit-VirtualHIDDevice/blob/bdfcb459b2eaca8ccda680a73b0dc898f330f4bb/version.json), [client source](https://github.com/pqrs-org/Karabiner-DriverKit-VirtualHIDDevice/blob/bdfcb459b2eaca8ccda680a73b0dc898f330f4bb/include/pqrs/karabiner/driverkit/virtual_hid_device_service/client.hpp), [socket constants](https://github.com/pqrs-org/Karabiner-DriverKit-VirtualHIDDevice/blob/bdfcb459b2eaca8ccda680a73b0dc898f330f4bb/include/pqrs/karabiner/driverkit/virtual_hid_device_service/constants.hpp).

## Native ownership and exact API surface

Recommended boundary: application Web UI -> unprivileged Python controller -> signed native control wrapper / authenticated local IPC -> application-owned native root helper -> upstream signed daemon -> upstream DriverKit keyboard. The helper owns selected physical Keydous input and report state; Python sends validated configuration, not arbitrary root commands or a general keystroke injection API.

The upstream daemon makes one client entry per peer (`src/Daemon/include/virtual_hid_device_service_clients_manager.hpp`); reset/terminate requests apply to that entry. An application client does not need pqrs.org's signing identity or its DriverKit user-client entitlement because the upstream daemon owns that connection. A root Python HTTP server would unnecessarily expose the privileged boundary and is not the implementation route.

For packaged installation, use an application-owned signed native wrapper with ServiceManagement on macOS 13+, not unattended `sudo` from a browser request. Upstream `examples/SMAppServiceExample/src/main.swift` and `files/LaunchDaemons/org.pqrs.service.daemon.Karabiner-VirtualHIDDevice-Daemon.plist` are concrete references for daemon registration. The package installs the daemon application and hidden extension manager, but `make-package.sh` does **not** install its sample LaunchDaemon plist; registration/lifetime ownership is additional work. Shared upstream components may already belong to another app: do not unconditionally overwrite an incompatible version or remove/deactivate them on Keydous removal.

Expose `not_installed`, `requires_approval`, `daemon_unavailable`, `driver_mismatch`, `input_permission_required`, `ready`, `active`, and `error` separately. Authorization of the current console user and the app's code identity belongs at the root helper's IPC boundary. Authenticate peers, keep configuration bounded, and stop interception on app disconnect, console-session change, native error or readiness loss. No global unrelated keyboard grab belongs in this slice.

The following report construction uses real symbols in the pinned headers. It is a source-audited API fragment, not a compiled/tested helper or a complete lifecycle. `client` is one long-lived service client, and these report calls belong on the helper's serialized state owner, after `virtual_hid_keyboard_ready(true)` and only for observed configured input edges.

```cpp
#include <pqrs/karabiner/driverkit/virtual_hid_device_driver.hpp>
#include <pqrs/karabiner/driverkit/virtual_hid_device_service.hpp>

namespace service = pqrs::karabiner::driverkit::virtual_hid_device_service;
namespace report = pqrs::karabiner::driverkit::virtual_hid_device_driver::hid_report;

// Once, before creating a client:
// pqrs::dispatcher::extra::initialize_shared_dispatcher();
// Construct service::client, connect its signals, then client.async_start().

void initialize_keyboard(service::client& client) {
  service::virtual_hid_keyboard_parameters parameters;
  // Select actual supported keyboard country/layout in application settings.
  parameters.set_country_code(pqrs::hid::country_code::us);
  client.async_virtual_hid_keyboard_initialize(parameters);
}

// Held-output state is persistent: preserve every other active top-case key.
void set_fn(service::client& client,
            report::apple_vendor_top_case_input& held, bool down) {
  const auto usage = type_safe::get(pqrs::hid::usage::apple_vendor_top_case::keyboard_fn);
  if (down) held.keys.insert(usage);
  else held.keys.erase(usage);
  client.async_post_report(held);
}
```

Connect `connected` to keyboard initialization; connect `driver_activated`, `driver_connected`, `driver_version_mismatched`, `virtual_hid_keyboard_ready`, `closed`, `connect_failed`, `error_occurred`, and `warning_reported` to explicit state transitions. All signals execute on the upstream dispatcher thread. `async_post_report` returns no per-report acknowledgement, and destroying the client immediately after queueing a release does not establish delivery. A production stop protocol must stop capture, reconcile reports, terminate the per-client virtual keyboard, observe readiness/disconnection with a bounded deadline, and then destroy the client before `terminate_shared_dispatcher()`.

Fn is top-case page `0x00ff`, usage `0x0003`; Apple vendor-keyboard `function` is page `0xff01`, usage `0x0003`. Both can normalize to logical Fn on input. The Fn output uses `apple_vendor_top_case_input` (report ID 3), **not** a `keyboard_input.modifiers` bit. The virtual keyboard advertises `AppleVendorSupported = true` in `src/DriverKit/.../org_pqrs_Karabiner_DriverKit_VirtualHIDKeyboard.cpp`. Ordinary keyboard, consumer and vendor-keyboard reports have their own state. A report contains the entire currently-held set for its page; two sources mapping to the same output require reference counting. Input owners must retain their selected output until key-up, including modifier-release-first cases.

For HID capture use a native IOHIDManager/IOHIDDevice run loop, matching a selected physical keyboard's registry identity/VID/PID/serial/transport. Open only its input interface with `IOHIDDeviceOpen(..., kIOHIDOptionsTypeSeizeDevice)` after output is ready. Never match/seize the virtual keyboard or the vendor feature-report control endpoint. Forward every unmodified key from a seized input device; otherwise those keys disappear. If the selected keyboard exposes consumer events on another interface, discover and handle it deliberately rather than assuming one interface covers all keys. Release seizure promptly when the output path fails. The proof for this distinction is Karabiner `device_grabber_details/entry.hpp:async_start_hid_device_events_monitor`.

Keydous physical Fn may emit no OS event. That must be measured on the target keyboard/mode. Mapping a firmware-observable ordinary key to virtual Fn can work independently; this does not establish physical Fn capture. Full Fn combinations also need ordinary-key and modifier ownership, keyboard layout/function-row preference policy, repeat, Caps Lock/LED synchronization, sleep/wake, disconnect and secure input acceptance. Raw USB HID does not provide Quartz-style repeat callbacks; do not synthesize an unrelated repeat policy by accident. Scope the initial Mac behavior to explicitly configured Keydous input.

## Mac-only build and acceptance commands

These are reproducible build/diagnostic instructions, not commands run in this Windows audit. Use a disposable pinned checkout and a temporary build directory. Do not run upstream `make run`: its sample intentionally emits keys and mouse movement.

```sh
git clone --no-checkout https://github.com/pqrs-org/Karabiner-DriverKit-VirtualHIDDevice.git
cd Karabiner-DriverKit-VirtualHIDDevice
git checkout bdfcb459b2eaca8ccda680a73b0dc898f330f4bb
pkgutil --check-signature dist/Karabiner-DriverKit-VirtualHIDDevice-8.5.0.pkg
spctl --assess --type install --verbose=2 dist/Karabiner-DriverKit-VirtualHIDDevice-8.5.0.pkg
xcrun stapler validate dist/Karabiner-DriverKit-VirtualHIDDevice-8.5.0.pkg

# Build the upstream client without executing its input-producing example.
cd examples/virtual-hid-device-service-client
xcodegen generate
xcodebuild -configuration Release -alltargets \
  SYMROOT="${TMPDIR%/}/keydous-vhid-audit-build" CODE_SIGNING_ALLOWED=NO
```

For a maintained helper using this header-only client, the minimal compilation shape is `xcrun clang++ -std=c++23 -mmacosx-version-min=13.0 -I "$DRIVER_SOURCE/include" -I "$DRIVER_SOURCE/vendor/vendor/include" <helper sources> -framework IOKit -framework CoreFoundation -o <temporary output>`. Add Foundation/ServiceManagement in an Objective-C++/Swift control wrapper as required by its actual sources. Do not describe this template as a passing build. Release signing, architecture selection, stable bundle identities, entitlements for the wrapper and notarization remain a separate Mac packaging packet.

During explicit on-Mac installation acceptance, the upstream manager activation executable is `/Applications/.Karabiner-VirtualHIDDevice-Manager.app/Contents/MacOS/Karabiner-VirtualHIDDevice-Manager activate`. It triggers macOS's extension approval flow; installation and activation do not prove keyboard readiness. Keep that action behind the integrated setup flow. Verify the app-owned privileged helper's service state and actual `virtual_hid_keyboard_ready` callback before enabling interception.

Python portability tests can verify non-Windows import/startup paths with a fake IoT client, two-process owner contention, safe Hook quoting of spaces/apostrophes, integrity-digest changes, deterministic bundle selection, error cleanup and shutdown. Report-state tests can verify Fn reference counts, modifier release ordering, multiple output pages and disconnect reconciliation. Mac acceptance must then verify actual Fn tap/Globe actions, function-row settings, both permissions and revocation, Keydous/Apple input distinctions, non-target keyboards unaffected, repeat, disconnect, sleep/wake, secure input and coexistence with other virtual-HID clients. No Windows mock replaces these checks.

## Official Mac IoT evidence and remaining blockers

The [official Keydous driver page](https://www.keydous.com/xz_keydous) advertises Mac drivers and distinguishes keyboard families. Its [NJ68/80 driver guide](https://www.keydous.com/newsinfo/4263947.html?templateId=1133604) also discusses Mac driver restrictions. This supports existence of Mac configuration software, **not** an assertion that the current NJ98 service exposes identical `127.0.0.1:3814/driver.DriverGrpc` APIs. The inspected frontend establishes that loopback transport generally, but this audit found no pinned Mac IoT installer or Mac protocol transcript. Do not silently substitute direct HID firmware writes.

Outstanding external evidence: user's Mac OS/CPU and keyboard model/connection/mode; official Mac IoT package/version and read-only discovery result; local TCC approvals; DriverKit package signature/notarization results; compile/runtime evidence for the native helper; actual Fn input visibility and Globe behavior; signed app/helper packaging identity. These block a supported Mac release, but do not block the Python portability and source-level native adapter implementation packets above.
