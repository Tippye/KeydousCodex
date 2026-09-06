#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: stage-app-components.sh /absolute/path/KeydousCodex.app" >&2
  exit 64
fi
app=$1
case "$app" in /*.app) ;; *) echo "target must be an absolute .app path" >&2; exit 64 ;; esac

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
macos_dir=$(dirname "$script_dir")
vhid_source=$(sh "$script_dir/fetch-virtual-hid.sh")
package=Karabiner-DriverKit-VirtualHIDDevice-8.5.0.pkg

test -d "$app/Contents"
test -x "$macos_dir/build/keydous-macos-fn"
test -x "$macos_dir/build/com.keydous.codex.fnhelper"
install -d "$app/Contents/MacOS" "$app/Contents/Library/LaunchServices" \
  "$app/Contents/Library/LaunchDaemons" "$app/Contents/Resources/Driver" \
  "$app/Contents/Resources/ThirdPartyLicenses"
install -m 0755 "$macos_dir/build/keydous-macos-fn" "$app/Contents/MacOS/keydous-macos-fn"
install -m 0755 "$macos_dir/build/com.keydous.codex.fnhelper" \
  "$app/Contents/Library/LaunchServices/com.keydous.codex.fnhelper"
install -m 0644 "$macos_dir/resources/com.keydous.codex.fnhelper.plist" \
  "$app/Contents/Library/LaunchDaemons/com.keydous.codex.fnhelper.plist"
install -m 0644 "$macos_dir/resources/org.pqrs.service.daemon.Karabiner-VirtualHIDDevice-Daemon.plist" \
  "$app/Contents/Library/LaunchDaemons/org.pqrs.service.daemon.Karabiner-VirtualHIDDevice-Daemon.plist"
install -m 0644 "$vhid_source/dist/$package" "$app/Contents/Resources/Driver/$package"
install -m 0644 "$vhid_source/LICENSE.md" \
  "$app/Contents/Resources/ThirdPartyLicenses/Karabiner-DriverKit-VirtualHIDDevice-LICENSE.md"
install -m 0644 "$macos_dir/THIRD_PARTY_NOTICES.md" \
  "$app/Contents/Resources/ThirdPartyLicenses/Keydous-macOS-Fn-NOTICES.md"
install -m 0644 "$macos_dir/licenses/BOOST-1.0.txt" \
  "$app/Contents/Resources/ThirdPartyLicenses/BOOST-1.0.txt"
install -m 0644 "$macos_dir/licenses/MIT-vendor-components.txt" \
  "$app/Contents/Resources/ThirdPartyLicenses/MIT-vendor-components.txt"

# Preserve the exact pinned header sources actually compiled into the helper.
source_notice="$app/Contents/Resources/ThirdPartySources/VirtualHIDDevice-client-bdfcb459"
install -d "$source_notice/upstream" "$source_notice/vendor"
cp -R "$vhid_source/include/." "$source_notice/upstream/"
for dependency in asio asio.hpp gsl nod type_safe; do
  cp -R "$vhid_source/vendor/vendor/include/$dependency" "$source_notice/vendor/"
done
install -d "$source_notice/vendor/pqrs"
for dependency in dispatcher dispatcher.hpp gsl.hpp hid hid.hpp unix_domain_stream unix_domain_stream.hpp; do
  cp -R "$vhid_source/vendor/vendor/include/pqrs/$dependency" "$source_notice/vendor/pqrs/"
done
