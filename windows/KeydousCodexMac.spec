# -*- mode: python ; coding: utf-8 -*-
"""Same Python/Web application packaged for macOS; execute on a Mac only."""
import os
import sys
from pathlib import Path

if sys.platform != "darwin":
    raise SystemExit("The Mac app must be built and verified on macOS")
root = Path(SPECPATH).resolve()
identity = os.environ.get("KEYDOUS_CODESIGN_IDENTITY") or None
a = Analysis([str(root / "run_bridge.py")], pathex=[str(root)],
             datas=[(str(root / "keydous_bridge/web"),"keydous_bridge/web")],
             binaries=[], hiddenimports=[], excludes=["tkinter","pytest"], optimize=0)
pyz = PYZ(a.pure)
main = EXE(pyz,a.scripts,[],exclude_binaries=True,name="KeydousCodex",console=False,
           argv_emulation=False,target_arch=None,codesign_identity=identity)
hook = EXE(pyz,a.scripts,[],exclude_binaries=True,name="KeydousCodexHook",console=True,
           argv_emulation=False,target_arch=None,codesign_identity=identity)
collection = COLLECT(main,hook,a.binaries,a.datas,name="KeydousCodex")
app = BUNDLE(collection,name="KeydousCodex.app",bundle_identifier="com.keydous.codex",
             info_plist={"CFBundleDisplayName":"Keyphore 路 Keydous","CFBundleShortVersionString":"0.3.0",
                         "LSMinimumSystemVersion":"13.0","NSHighResolutionCapable":True,
                         "NSInputMonitoringUsageDescription":"Map a selected Keydous keyboard key to Fn/Globe."})
