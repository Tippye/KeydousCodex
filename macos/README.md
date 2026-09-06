# Keydous native macOS Fn component

This directory contains the source-only macOS input component for the Keydous
Codex application. It captures one explicitly selected NJ98 USB keyboard
interface, forwards the keyboard-page input through the pinned upstream virtual
keyboard, and maps one ordinary OS-visible HID usage to Apple's native Fn/Globe
usage. It does not claim that the NJ98's physical firmware Fn key is observable.

The native component is not a standalone product or settings application. The
unprivileged Python/Web application invokes the signed control executable. The
control executable registers the two embedded ServiceManagement daemon plists
and communicates with the application-owned root helper over an authenticated
Unix socket. The helper accepts only status, enable, and disable requests and a
fixed configuration schema; it has no shell, file-write, firmware-write, raw
report, or arbitrary key-injection request.

## Control protocol

The packaged executable is `Contents/MacOS/keydous-macos-fn`:

```text
keydous-macos-fn status --json
keydous-macos-fn enable --config /absolute/path/config.json --json
keydous-macos-fn disable --json
keydous-macos-fn remove-helper --json
```

`status` exits zero after emitting valid status JSON, including for
`not_installed` and `requires_approval`. `enable` exits zero only after the
virtual keyboard reported ready and the selected physical interface was seized.
`disable` exits zero only after capture stopped, empty held reports were queued,
and the upstream client observed virtual-keyboard termination. A queued install,
background approval request, or extension activation never returns success.
`remove-helper` first requires the same acknowledged disable, then unregisters
only the app-owned Keydous launch daemon. It deliberately leaves the shared pqrs
daemon, extension, and package installed.

The only accepted configuration is:

```json
{
  "schemaVersion": 1,
  "device": {
    "registryEntryId": "123456789",
    "vendorId": 12625,
    "productId": 16405,
    "transport": "USB"
  },
  "source": {"usagePage": 7, "usage": 228},
  "target": "native_fn"
}
```

The registry entry ID is a required decimal string chosen from `status.candidates`.
There is no automatic selection when multiple interfaces exist. The current
allowlist is exactly VID `0x3151`, PID `0x4015`, USB transport. The source must be
one keyboard-page usage from 4 through 231; Caps Lock is rejected because its HID
toggle semantics need a separate policy. The target is fixed to native Fn,
encoded as Apple vendor top-case page `0x00ff`, usage `0x0003`.

Status uses `state` values `not_installed`, `requires_approval`, `ready`,
`active`, or `error`. It reports service states, driver activation/connection,
protocol mismatch, virtual-keyboard readiness, input capture, the acknowledged
configuration, and candidates independently. `errorCode` carries details such as
`daemon_unavailable`, `driver_mismatch`, `input_permission_required`,
`device_not_found`, or `controller_disconnected`.

The first version deliberately fixes the virtual keyboard country code to US
and is therefore scoped to the current ANSI NJ98 layout. Other physical layouts
are not supported by this source packet. Caps Lock input passes through, but
physical Caps LED synchronization is not implemented; Caps Lock cannot be selected
as the mapped source. These are explicit incomplete behaviors as well as real-Mac
acceptance limits.

The wrapper derives `controllerPid` from its actual parent; it is not accepted
from a config file or CLI flag. The helper verifies that PID is the wrapper's
parent, has the authenticated console user's UID, and retains the same process
start timestamp. If that Python application process exits, the helper releases
the physical seizure and all virtual outputs.

## Capture and failure behavior

The helper waits for the upstream daemon and the real
`virtual_hid_keyboard_ready(true)` callback before it seizes input. IOHID matching
is restricted to the chosen Generic Desktop Keyboard service. Exact registry ID,
VID, PID, and USB transport are rechecked at seize time; upstream virtual devices
and Karabiner-named devices are excluded. A separate consumer-control interface
is left to macOS and therefore passes through directly. Consumer usages present
on the seized combined keyboard interface are forwarded through the complete
consumer report.

Every other supported input usage on the seized interface passes through.
Keyboard modifiers and keys, consumer keys, Generic Desktop system keys, Apple
vendor top-case keys, and Apple vendor-keyboard keys keep separate complete held
reports. An interface containing any other input page is rejected before seizure
instead of swallowing values the virtual keyboard cannot forward. Output ownership is
reference-counted. Key-up releases the output selected on key-down even after a
configuration change, so releasing a modifier before another key cannot strand
Fn. Raw repeated downs do not create another owner; the held virtual key lets the
macOS keyboard stack supply repeat.

On device removal, controller exit, loginwindow/console-session change, input
permission revocation, driver mismatch, daemon disconnect, readiness loss,
report-capacity overflow, or report-post failure, the helper stops and
closes the seized device first. It then reconciles tracked reports and terminates
its per-client virtual keyboard. Teardown tracks client ownership separately
from readiness, requires a fresh daemon response, and closes the daemon connection
to destroy its upstream client entry if that response cannot arrive. Status becomes
`error` rather than retaining a stale `active` claim.

## Build and package

The build uses C++23 and macOS 13. It fetches and checks out
`Karabiner-DriverKit-VirtualHIDDevice` commit
`bdfcb459b2eaca8ccda680a73b0dc898f330f4bb`, verifies the bundled 8.5.0 package
SHA-256 `d73d6d9428f0f80b87b8a8ba8a1031f2cbc3bc1fa6b74842d1f1b764b2916fc9`,
and compiles against its `include` and `vendor/vendor/include` trees:

```sh
sh macos/scripts/build-native.sh
sh macos/scripts/stage-app-components.sh /absolute/path/KeydousCodex.app
```

For the complete same-application bundle, run from the repository root on
macOS 13 or later with Python 3.12 or later, CMake, and the Xcode command-line
tools installed:

```sh
KEYDOUS_CODESIGN_IDENTITY='Developer ID Application: Example Corp (TEAMID)' \
KEYDOUS_PYTHON=/path/to/python3.12 \
sh windows/Build-Mac.sh
```

That build still requires a real Developer ID identity, final notarization, and
the signed-app/hardware acceptance work listed below before distribution.

The fetch checkout stays in ignored `macos/.deps`; the staging script copies
only the two first-party binaries, two daemon plists, the unmodified signed
upstream package, and required notices. It does not vendor the research checkout
into a release.

The final application must use stable identifiers and one Apple Team ID:

- app: `com.keydous.codex`
- control executable designated identifier: `com.keydous.codex.fncontrol`
- root helper designated identifier: `com.keydous.codex.fnhelper`

Sign the helper and control executable with hardened runtime before signing the
outer application, then notarize the complete distribution. No first-party
DriverKit entitlement is declared: the unmodified upstream daemon owns the
DriverKit connection. At runtime the helper requires a valid non-ad-hoc signature
and rejects a control peer unless its Team ID matches the helper and its signing
identifier is exactly `com.keydous.codex.fncontrol`.

On the first explicit enable, the wrapper hashes and assesses the bundled package
with `pkgutil` and `spctl`, then opens Apple's Installer if version 8.5.0 is absent.
The operation remains `not_installed` until installation completes. A later
enable registers the embedded upstream daemon and Keydous helper with
ServiceManagement, surfaces background-item approval, invokes the installed
upstream extension manager's `activate` action, and waits for helper acknowledgement.
It refuses an installed upstream version other than 8.5.0 rather than overwriting
a possibly shared installation.

Automatic replacement of an incompatible shared VirtualHIDDevice package is not
implemented. Status reports `driver_mismatch`; the application must present a
reviewable upgrade/removal flow after checking which other software owns that
installation. Likewise, `input_seize_failed` or `input_conflict` is an explicit
remapper-conflict result rather than permission to take over another remapper.

## Verification boundary

The portable report-state and keyboard-teardown state tests can be built on any
C++23 host. On this Windows source host they were compiled with MSVC and passed.
The Objective-C++, IOKit,
ServiceManagement, signing, package assessment, DriverKit readiness, device
seizure, native Fn/Globe behavior, permissions, sleep/wake, secure input, media
interfaces, and real NJ98 modes still require the Mac acceptance matrix in
`../windows/docs/macos-implementation-audit.md`. Do not advertise macOS Fn support
until those checks pass on the signed packaged application and actual hardware.
