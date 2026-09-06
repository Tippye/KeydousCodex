#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
macos_dir=$(dirname "$script_dir")
vhid_source=$(sh "$script_dir/fetch-virtual-hid.sh")
build_dir="$macos_dir/.cmake-build"

cmake -S "$macos_dir" -B "$build_dir" \
  -DCMAKE_BUILD_TYPE=Release \
  -DKEYDOUS_VHID_SOURCE="$vhid_source" \
  ${KEYDOUS_CMAKE_ARGS:-}
cmake --build "$build_dir" --config Release --parallel
ctest --test-dir "$build_dir" --output-on-failure

test -x "$macos_dir/build/keydous-macos-fn"
test -x "$macos_dir/build/com.keydous.codex.fnhelper"
