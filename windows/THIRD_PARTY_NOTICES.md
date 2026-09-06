# Third-party notices

Keydous Codex Bridge is a Windows adaptation built from Keyphore. Keyphore is
Copyright (c) 2026 Barry Barry Wu and is licensed under GPL-3.0-only. This
adaptation is based on upstream commit
`9ca11f275809ebc2649bf365effdee8cc7682084`. The complete GNU GPL version 3
license is included in `licenses/LICENSE` and the corresponding source archive
is distributed alongside the Windows binary archive.

The packaged application contains or uses the following third-party runtime
components. Their full license texts are included under
`licenses/third-party/`:

- Python 3.12 — Python Software Foundation License Version 2 and included
  historical notices (`PYTHON-LICENSE.txt`).
- Pillow 12.3.0 — HPND license (`PILLOW-LICENSE.txt`).
- PyInstaller 6.22.2 bootloader — GPL version 2 or later with the special
  exception described in its license (`PYINSTALLER-COPYING.txt`).

The official Keydous IoT driver is required at runtime but is not included in
these archives. This program communicates with its local loopback service. It
is an independent third-party program and is not an official Keydous driver or
an official Keydous plugin.

Codex pet images are not included. When requested by the user, the program can
copy compatible pet assets from that user's locally installed Codex app into
its own local data directory. Those assets are not added to release archives.
