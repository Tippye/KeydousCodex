# Keydous Codex Bridge

[简体中文](README.zh-CN.md) · [Windows setup](windows/README.md)

This is a local fork of [BarryBarrywu/Keyphore](https://github.com/BarryBarrywu/Keyphore), based on upstream commit [`9ca11f275809ebc2649bf365effdee8cc7682084`](https://github.com/BarryBarrywu/Keyphore/tree/9ca11f275809ebc2649bf365effdee8cc7682084). The original project maps Codex task events to NuPhy keyboard lighting on macOS. This fork adds a Windows desktop bridge for **Keydous NJ98 over wired USB**, including status lights, key/knob mappings and manual screen uploads.

This is an independent third-party project, not an official Keydous, NuPhy or OpenAI product. The upstream attribution and GPL-3.0-only license are retained.

## What works

| Feature | Scope |
| --- | --- |
| Codex status | Local Hooks aggregate working, approval-waiting and turn-ended events. |
| Keyboard RGB | Optional status lighting with a minimum 10-second write interval and original-setting restoration. |
| Rotary knob | Turn left/right to navigate Codex tasks or tabs. Press to focus Codex, or minimize it when already in the foreground. |
| Key mappings | NJ98 normal/Fn layers, with saved preimages and verified restoration. |
| Screen content | Preview/export pet animations and manually upload a snapshot or animation to a selected GIF slot. |

## The keyboard screen cannot mirror Codex in real time

**The current Keydous NJ98 screen integration cannot keep its displayed state synchronized with Codex in real time.** Its image-upload path is too slow for frequent refreshes: sending and writing image/animation data takes time, and no suitable live-framebuffer or automatic preloaded-page switching interface has been verified.

An uploaded animation can play on the keyboard, but it does not automatically change when Codex starts working, waits for a reply or finishes. Status labels, lock indicators and battery/connection information embedded in an upload describe the moment it was generated. The app therefore performs screen uploads only when requested; it does not re-upload an animation on every Codex event.

This limitation concerns **screen content**. The desktop status display, optional RGB signals and knob shortcuts remain available. No precise screen refresh rate or upload duration has been established; the limitation applies to this tested model and integration, not every keyboard brand.

## Start here

The current Windows version is **0.4.0**. It stays active in the Windows system tray when its window is closed; use the tray Quit command or the in-app Quit button to stop it. It requires Windows 10/11, WebView2 Runtime, the running Keydous IoT driver and an NJ98 connected by USB. Exact supported identity: driver model ID `1021`, VID/PID `3151:4015`.

Follow the [Windows guide](windows/README.md) for setup, Hook integration, knob controls, recovery and building. Local packages are generated in `windows/release/`; extract the full Windows ZIP and run `KeydousCodex.exe` with its companion files present.

The Keydous macOS work in [`macos/`](macos/README.md) is experimental source, without complete Mac build, signing or hardware acceptance. The original NuPhy implementation remains in the repository as upstream source; its support claims do not apply to the Keydous port.

## Other keyboard brands

Owners of other brands, including Keychron, can fork this project and ask ChatGPT/Codex to help adapt it to their keyboard. Provide the exact model, connection mode, USB identity and official driver/SDK or protocol documentation. Lighting, screen uploads and knob remapping are separate capabilities and need separate verification; changing the model allowlist alone does not make a device compatible.

A useful starting request:

> Adapt this Keyphore fork to my [brand/model] keyboard over [connection]. Inspect its official driver or SDK and device identity first. Reuse the Codex state logic, implement the supported lighting/knob/screen functions, and measure screen update time before claiming real-time synchronization. Preserve the existing configuration and verify restoration.

Start with [`models.py`](windows/keydous_bridge/models.py), [`iot.py`](windows/keydous_bridge/iot.py) and the [protocol research](windows/docs/protocol-research.md). A different device may offer better screen support, but that must be established on that device.

## Repository layout

| Path | Purpose |
| --- | --- |
| `windows/` | Shared Python application, Windows desktop host, UI, tests and packaging. |
| `macos/` | Experimental Keydous macOS native input components. |
| `app/`, `runtime/`, `src/`, `plugin/` | Retained upstream Swift/Rust NuPhy implementation. |
| `tests/` | Upstream tests and fixtures; the Windows Hook tests reuse a parity fixture. |
| `docs/adr/` | Architecture decisions, including the [Keydous port boundary](docs/adr/0009-add-windows-keydous-port.md). |

See [AGENTS.md](AGENTS.md) for repository conventions, [the design](windows/DESIGN.md) for implementation boundaries and [acceptance records](windows/docs/acceptance.md) for tested behavior.

## License and attribution

Derived from Keyphore by Barry Barry Wu. First-party code is [GPL-3.0-only](LICENSE); preserve copyright and license notices and provide corresponding source with distributed binaries. Dependency notices are in [`LICENSES/`](LICENSES), [Windows notices](windows/THIRD_PARTY_NOTICES.md) and [macOS notices](macos/THIRD_PARTY_NOTICES.md). Codex pet assets are imported locally by users and are not bundled in releases.
