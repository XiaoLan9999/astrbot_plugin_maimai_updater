#!/bin/sh
set -eu

compiler="${CC:-x86_64-w64-mingw32-gcc}"
output="${1:-chime_bridge.exe}"
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

exec "$compiler" \
    -std=c11 \
    -O2 \
    -Wall \
    -Wextra \
    -Werror \
    -pedantic \
    -static-libgcc \
    -Wl,--no-insert-timestamp \
    -s \
    -o "$output" \
    "$script_dir/chime_bridge.c"
