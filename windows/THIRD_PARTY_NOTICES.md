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
- pywebview 6.1 — BSD-3-Clause (`PYWEBVIEW-LICENSE.txt`), https://github.com/r0x0r/pywebview.
- pythonnet 3.0.5 — MIT (`PYTHONNET-LICENSE.txt`), https://github.com/pythonnet/pythonnet/tree/v3.0.5.
- clr-loader 0.2.10 — MIT (`CLR-LOADER-LICENSE.txt`), https://github.com/pythonnet/clr-loader/tree/v0.2.10.
- Microsoft.Web.WebView2 SDK 1.0.2957.106 — Microsoft BSD-style license
  (`WEBVIEW2-SDK-LICENSE.txt`), https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.2957.106/License.
  The separately installed Microsoft Edge WebView2 Runtime is not redistributed here.
- proxy-tools 0.1.0 — upstream BSD-3-Clause (`PROXY-TOOLS-LICENSE.txt`), https://github.com/jtushman/proxy_tools.
- Bottle 0.13.4 — MIT (`BOTTLE-LICENSE.txt`), https://github.com/bottlepy/bottle.
- typing_extensions 4.16.0 — PSF license (`TYPING-EXTENSIONS-LICENSE.txt`), https://github.com/python/typing_extensions.
- CFFI 2.1.1 — MIT No Attribution (`CFFI-LICENSE.txt`), https://github.com/python-cffi/cffi.
- pycparser 3.0 — BSD-3-Clause (`PYCPARSER-LICENSE.txt`), https://github.com/eliben/pycparser.
- setuptools runtime support — MIT (`SETUPTOOLS-LICENSE.txt`), https://github.com/pypa/setuptools.

The Windows executable reuses the original Keyphore application icon under the
same GPL-3.0-only license and attribution as the upstream application.

The official Keydous IoT driver is required at runtime but is not included in
these archives. This program communicates with its local loopback service. It
is an independent third-party program and is not an official Keydous driver or
an official Keydous plugin.

Codex pet images are not included. When requested by the user, the program can
copy compatible pet assets from that user's locally installed Codex app into
its own local data directory. Those assets are not added to release archives.
