# Repository scope

This is a fork of BarryBarrywu/Keyphore. Keep upstream attribution and GPL notices.
The Windows Keydous NJ98 port lives in `windows/`; `macos/` contains experimental
Keydous native input components. The original NuPhy app/runtime and shared test
fixtures remain maintained source, not disposable legacy files. Read `CONTEXT.md`
and `docs/adr/0009-add-windows-keydous-port.md` for platform boundaries.

For Windows changes, follow `windows/README.md`, `windows/DESIGN.md` and
`windows/docs/acceptance.md`. Run the relevant Python tests; UI changes also use
`node tests/test_web_state.js` from `windows/`. Hardware claims require device
evidence. Screen uploads are manual snapshots/animations, not real-time Codex sync.

Keep generated caches, build outputs and release archives out of Git. Preserve
runtime data, imported resources and device recovery backups during cleanup.
Check references before removing assets or source. Do not publish fork work to
the upstream issue tracker or remote unless the user requests that destination.

## Agent skills (upstream conventions)

### Issue tracker

Issues and PRDs are tracked in GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five default triage labels. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository. See `docs/agents/domain.md`.

### Upstream NuPhy development acceptance (macOS)

Before opening a development build or running physical keyboard acceptance, use
`tools/keyphore-development-app build-open`. It installs the current build at the stable
user-scoped development App path and refuses to continue while a legacy or current Companion
could still own HID. Do not open Keyphore directly from DerivedData or another temporary path.

Build-only and automated test runs still use the global temporary-build rules. After physical
acceptance, quit Keyphore through the App so it can complete signal-off acknowledgement and stop
its Companion.
