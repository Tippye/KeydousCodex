# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the Windows Keydous bridge and its Hook helper."""

from pathlib import Path


windows_root = Path(SPECPATH).resolve()

datas = [
    (str(windows_root / "keydous_bridge" / "web"), "keydous_bridge/web"),
]

analysis = Analysis(
    [str(windows_root / "run_bridge.py")],
    pathex=[str(windows_root)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)

main_exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="KeydousCodex",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

hook_exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="KeydousCodexHook",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

collection = COLLECT(
    main_exe,
    hook_exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="KeydousCodex",
)
