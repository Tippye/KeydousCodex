# Add a Windows Keydous port

Accepted for this local adaptation on 2026-09-06 at the user's request; not an upstream-maintainer decision.

The existing production app is macOS Swift and the Rust lifecycle also depends on Unix. A Windows Keydous port lives in `windows/`, with a Python runtime and a loopback browser UI. It derives its eight-hook normalization, durable per-owner status and aggregate priority from the existing Keyphore implementation. Upstream fixtures and source semantics are used as behavioral evidence.

This is a platform-scoped extension to ADR-0007, not a replacement of the upstream Swift app. ADR-0004 remains: hooks update durable allowlisted state, and never open the keyboard or depend on a transient HTTP socket. The Windows companion alone calls the official Keydous IoT service. Existing macOS/NuPhy code and physical acceptance tools remain unchanged; the Mac-only `build-open` workflow does not apply to the Windows port. Windows has its own build and acceptance commands.

NJ98 has a persistent image-upload protocol but no verified volatile framebuffer or page-switch API. Pet rendering/export and explicit resource upload are distinct from dynamic status lighting. Native lock/connection/battery overlay coexistence remains unverified. Device writes use an exact identity allowlist; recognition alone does not enable unsupported models.

The Windows extension preserves and distributes GPL-3.0-only licensing and source attribution. Codex's proprietary pet images are imported from the user's installed application, not bundled in this fork's distribution.

On 2026-09-06 the user approved extending this same Keydous application to macOS, including an application-managed internal virtual HID component for native Fn/Globe. The Python/Web package remains the shared business/UI owner (its existing directory is still named windows); macos/ contains only native input/lifecycle/build pieces. The original Swift/NuPhy app remains an upstream reference, not a second Keydous application. Platform-independent tests and Windows simulations do not grant Mac runtime/release acceptance. A Keydous Mac physical test must use the newly packaged stable application, with one HID owner, explicit permissions, and normal app shutdown; the older NuPhy build-open tool cannot build this distinct shared implementation.

Windows/Web UI now follows the original compact state panel and grouped settings workflow, retaining explicit reviewed Hook consent. Firmware mapping uses exact NJ98 identity, single-key operations, full checked preimages, and complete readback/restoration. Host Fn is a separate native input responsibility and does not change firmware mappings. The HTTP process stays unprivileged; native control authenticates callers and permits bounded configuration only.

Windows RGB idle restores captured original settings, a deliberate hardware-specific departure from upstream NuPhy signal-off behavior because a separate Keydous lighting profile has not been established. The record survives interrupted restoration. Hook review and consent remain explicit, and affect only this port's plugin and owned hook keys.
