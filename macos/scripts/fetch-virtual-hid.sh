#!/bin/sh
set -eu

commit=bdfcb459b2eaca8ccda680a73b0dc898f330f4bb
package=Karabiner-DriverKit-VirtualHIDDevice-8.5.0.pkg
sha=d73d6d9428f0f80b87b8a8ba8a1031f2cbc3bc1fa6b74842d1f1b764b2916fc9
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
macos_dir=$(dirname "$script_dir")
checkout=${KEYDOUS_VHID_SOURCE:-"$macos_dir/.deps/Karabiner-DriverKit-VirtualHIDDevice"}

if [ -n "${KEYDOUS_VHID_SOURCE:-}" ]; then
  test -d "$checkout/.git"
  test "$(git -C "$checkout" rev-parse HEAD)" = "$commit"
  test "$(shasum -a 256 "$checkout/dist/$package" | awk '{print $1}')" = "$sha"
  printf '%s\n' "$checkout"
  exit 0
fi

if [ ! -d "$checkout/.git" ]; then
  mkdir -p "$(dirname "$checkout")"
  git clone --no-checkout https://github.com/pqrs-org/Karabiner-DriverKit-VirtualHIDDevice.git "$checkout"
fi
git -C "$checkout" fetch --depth 1 origin "$commit"
git -C "$checkout" checkout --detach "$commit"
test "$(git -C "$checkout" rev-parse HEAD)" = "$commit"
test "$(shasum -a 256 "$checkout/dist/$package" | awk '{print $1}')" = "$sha"
printf '%s\n' "$checkout"
