# Windows Keydous UI parity

The Windows desktop and optional browser UI follow the interaction hierarchy of the original macOS Keyphore application. Since 0.3.0, Windows starts an independent WebView2 window by default, using the original Keyphore application icon.

Since 0.4.0, closing the Windows surface hides it to the system tray while the shared status service continues. The tray default action and Open command restore the same window; tray Quit and the in-app Quit command remain the explicit full-lifecycle exit paths.

## Source mapping

| Original source | Windows/browser equivalent |
| --- | --- |
| `KeyphorePopover.swift` | A 392 px compact home surface with the Keyphore mark, one status title and detail, a keyboard screen presentation, a device/connection row, and a gear button that opens settings. |
| `SignalSettingsView.swift` | A separate settings surface with icon tabs, muted section labels, rounded grouped cards, system/light/dark appearance choices, and a dedicated quit action. |
| `DiagnosticsView.swift` | Diagnostics remain user initiated. The browser copies a reviewed local snapshot and redacts the selected session path rather than creating the macOS ZIP report. |
| Guided setup in `KeyphorePopover.swift` and `SystemGuidedSetup.swift` | Codex Hook setup stays inside a dedicated Integration group. Eight definitions, full commands, runtime paths and integrity hashes are shown before the consent checkbox can enable installation. |

## Windows and Keydous differences

- Keydous uses a 160 × 80 device screen, so the home illustration is the live generated screen preview rather than the Air65 key-light drawing.
- The bridge supports manual screen upload only unless the connected device explicitly reports dynamic-screen capability. The UI states the 30–120 second estimate, overwrite behavior, wired-connection requirement, and static Dashboard snapshot limit beside the upload action.
- Pet selection, imports, exports, desktop/JSONL/manual sources, RGB restore, and device capability details live in grouped settings because they have no direct counterpart in the original Air65 signal-light application.
- The Mapping group exposes only server-provided control labels and action tokens. Opening it performs a fresh full-matrix read. A single write requires an explicit Apply action carrying the read revision; any rejected, stale, malformed, or unavailable response invalidates the editor until another successful read. Raw four-byte mapping values are never displayed or editable.
- Mapping restore is enabled only when the server reports a recovery snapshot for the selected device. The UI does not claim success if read, apply, or restore is unavailable.
- Unknown connection type, battery, lock state, capabilities, and mapping values remain labeled unknown. Missing data is never converted into a supported/ready state.
- Appearance supports system, light, and dark. The Windows desktop host persists its WebView2 profile under the application data directory. Desktop and explicit Web access share HTML/CSS/JavaScript; the desktop layout fills the resizable native client area. The original SwiftUI views are the design reference, not compiled Windows controls.
- Hook consent, hardware writes, RGB changes, mapping changes, shutdown, and mapping restore keep explicit user actions. Merely opening or connecting the UI does not install Hooks, upload a screen, change RGB, or write a key mapping.
