"""Prepare license material and reproducible Windows release archives."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
from pathlib import Path
import shutil
import sys
import sysconfig
import tomllib
import zipfile


WINDOWS_ROOT = Path(__file__).resolve().parent
REPO_ROOT = WINDOWS_ROOT.parent
NOTICE_ROOT = WINDOWS_ROOT / "build-notices"
DIST_ROOT = WINDOWS_ROOT / "dist" / "KeydousCodex"
RELEASE_ROOT = WINDOWS_ROOT / "release"

EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "data",
    "build",
    "dist",
    "__pycache__",
    "build-notices",
    ".cmake-build",
    ".deps",
    "stage",
}


def project_version() -> str:
    with (WINDOWS_ROOT / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def _copy_distribution_license(distribution_name: str, destination_name: str) -> None:
    distribution = importlib.metadata.distribution(distribution_name)
    candidates = [
        item
        for item in (distribution.files or [])
        if Path(str(item)).name.lower().startswith(("license", "copying"))
    ]
    if not candidates:
        raise RuntimeError(f"No license file found in {distribution_name} metadata")
    source = Path(distribution.locate_file(candidates[0])).resolve()
    if not source.is_file():
        raise RuntimeError(f"License file is missing for {distribution_name}: {source}")
    shutil.copyfile(source, NOTICE_ROOT / destination_name)


def prepare_notices() -> None:
    NOTICE_ROOT.mkdir(parents=True, exist_ok=True)

    python_license = next((path for path in (Path(sys.base_prefix) / "LICENSE.txt",
                          Path(sysconfig.get_path("stdlib")) / "LICENSE.txt") if path.is_file()), None)
    if python_license is None:
        raise RuntimeError("Python license file is missing from this runtime; use a distribution including LICENSE.txt")
    shutil.copyfile(python_license, NOTICE_ROOT / "PYTHON-LICENSE.txt")
    _copy_distribution_license("Pillow", "PILLOW-LICENSE.txt")
    _copy_distribution_license("pyinstaller", "PYINSTALLER-COPYING.txt")
    if sys.platform == "win32":
        for name in ("pywebview", "bottle", "typing_extensions", "cffi", "pycparser", "setuptools"):
            _copy_distribution_license(name, name.upper().replace("_", "-") + "-LICENSE.txt")
        for name in ("PROXY-TOOLS-LICENSE.txt", "WEBVIEW2-SDK-LICENSE.txt", "PYTHONNET-LICENSE.txt", "CLR-LOADER-LICENSE.txt"):
            shutil.copyfile(WINDOWS_ROOT / "licenses" / name, NOTICE_ROOT / name)



def _source_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(REPO_ROOT)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if relative.parts[:2] == ("windows", "release"):
            continue
        if path.name.endswith((".pyc", ".pyo")):
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(REPO_ROOT).as_posix())


def _write_zip(archive: Path, entries: list[tuple[Path, str]]) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for source, archive_name in entries:
            info = zipfile.ZipInfo.from_file(source, archive_name)
            # Stable timestamps make identical source trees produce identical archives.
            info.date_time = (2026, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            with source.open("rb") as handle:
                bundle.writestr(info, handle.read(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _stage_release_documents() -> None:
    """Put human-readable notices beside the EXEs, outside PyInstaller's _internal."""
    executables = [DIST_ROOT / "KeydousCodex.exe", DIST_ROOT / "KeydousCodexHook.exe"]
    missing = [str(path) for path in executables if not path.is_file()]
    if missing:
        raise RuntimeError("Build output is incomplete:\n  " + "\n  ".join(missing))

    license_root = DIST_ROOT / "licenses"
    third_party_root = license_root / "third-party"
    third_party_root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO_ROOT / "LICENSE", license_root / "LICENSE")
    shutil.copyfile(WINDOWS_ROOT / "README.md", DIST_ROOT / "README.md")
    shutil.copyfile(WINDOWS_ROOT / "THIRD_PARTY_NOTICES.md", DIST_ROOT / "THIRD_PARTY_NOTICES.md")
    document_root = DIST_ROOT / "docs"
    document_root.mkdir(parents=True, exist_ok=True)
    for name in ("acceptance.md", "protocol-research.md", "codex-research.md"):
        shutil.copyfile(WINDOWS_ROOT / "docs" / name, document_root / name)
    for source in sorted(NOTICE_ROOT.glob("*.txt")):
        name = source.name
        if not source.is_file():
            raise RuntimeError(f"Prepared third-party license is missing: {source}")
        shutil.copyfile(source, third_party_root / name)


def release() -> tuple[Path, Path, Path]:
    version = project_version()
    _stage_release_documents()
    required = [
        DIST_ROOT / "KeydousCodex.exe",
        DIST_ROOT / "KeydousCodexHook.exe",
        DIST_ROOT / "licenses" / "LICENSE",
        DIST_ROOT / "licenses" / "third-party" / "PYTHON-LICENSE.txt",
        DIST_ROOT / "licenses" / "third-party" / "PILLOW-LICENSE.txt",
        DIST_ROOT / "licenses" / "third-party" / "PYINSTALLER-COPYING.txt",
        DIST_ROOT / "README.md",
        DIST_ROOT / "THIRD_PARTY_NOTICES.md",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("Build output is incomplete:\n  " + "\n  ".join(missing))

    binary_archive = RELEASE_ROOT / f"KeydousCodex-{version}-windows-x64.zip"
    source_archive = RELEASE_ROOT / f"KeydousCodex-{version}-source.zip"
    binary_prefix = f"KeydousCodex-{version}-windows-x64"
    source_prefix = f"KeydousCodex-{version}-source"

    binary_entries = [
        (path, f"{binary_prefix}/{path.relative_to(DIST_ROOT).as_posix()}")
        for path in sorted(DIST_ROOT.rglob("*"))
        if path.is_file()
    ]
    source_entries = [
        (path, f"{source_prefix}/{path.relative_to(REPO_ROOT).as_posix()}")
        for path in _source_files()
    ]
    _write_zip(binary_archive, binary_entries)
    _write_zip(source_archive, source_entries)

    checksum_file = RELEASE_ROOT / f"KeydousCodex-{version}-SHA256SUMS.txt"
    checksum_lines = []
    for archive in (binary_archive, source_archive):
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        checksum_lines.append(f"{digest}  {archive.name}")
    checksum_file.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8", newline="\n")
    return binary_archive, source_archive, checksum_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare-notices", "release"))
    args = parser.parse_args()
    if args.command == "prepare-notices":
        prepare_notices()
        print(f"Prepared notices in {NOTICE_ROOT}")
    else:
        artifacts = release()
        for artifact in artifacts:
            print(artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
