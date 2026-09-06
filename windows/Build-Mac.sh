#!/bin/sh
# Build the same application on macOS. Signing/permissions are real prerequisites.
set -eu
if [ "$(uname -s)" != Darwin ]; then
  echo 'Build-Mac.sh requires macOS; Windows mocks do not validate a Mac release.' >&2
  exit 1
fi
build_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python_runtime=${KEYDOUS_PYTHON:-python3}
: "${KEYDOUS_CODESIGN_IDENTITY:?Set a Developer ID Application signing identity}"
cd "$build_root"
"$python_runtime" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else "Python 3.12 or later is required")'
"$python_runtime" -m pip install -r requirements.txt 'pyinstaller==6.22.2'
"$python_runtime" package_release.py prepare-notices
"$python_runtime" -m PyInstaller --clean --noconfirm KeydousCodexMac.spec
sh ../macos/scripts/build-native.sh
sh ../macos/scripts/stage-app-components.sh "$build_root/dist/KeydousCodex.app"
app="$build_root/dist/KeydousCodex.app"
install -d "$app/Contents/Resources/ThirdPartyLicenses"
install -m 0644 ../LICENSE "$app/Contents/Resources/ThirdPartyLicenses/Keyphore-GPL-LICENSE.txt"
for notice in build-notices/*.txt; do
  install -m 0644 "$notice" "$app/Contents/Resources/ThirdPartyLicenses/"
done
codesign --force --options runtime --timestamp --sign "$KEYDOUS_CODESIGN_IDENTITY" \
  --identifier com.keydous.codex.fncontrol "$app/Contents/MacOS/keydous-macos-fn"
codesign --force --options runtime --timestamp --sign "$KEYDOUS_CODESIGN_IDENTITY" \
  --identifier com.keydous.codex.fnhelper "$app/Contents/Library/LaunchServices/com.keydous.codex.fnhelper"
codesign --force --options runtime --timestamp --sign "$KEYDOUS_CODESIGN_IDENTITY" "$app"
codesign --verify --deep --strict --verbose=2 "$app"
echo 'Signed app assembled. Follow macos/README.md for notarization and real-Mac acceptance before release.'
