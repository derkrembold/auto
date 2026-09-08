#!/bin/bash
# Headless clean-build of STM32/firmware/ — no STM32CubeIDE GUI needed.
# Uses the GCC/make toolchain STM32CubeIDE already bundles internally
# (this is literally what the IDE calls when you click "Build"), so no
# separate toolchain install is required. See STM32/CLAUDE.md's Build &
# Flash section for background.
#
# Always cleans first — a stale intermediate object silently surviving
# a source change is a classic embedded-C footgun; the build is fast
# enough here that always doing a full rebuild costs little and removes
# that whole failure class. Output: STM32/firmware/Debug/demoboard.elf
#
# Compile messages (warnings/errors) are streamed live to the terminal
# AND saved to STM32/build.log (a line-by-line read loop, since `tee`
# isn't available in this shell). build.log is gitignored, regenerated
# every run.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$REPO_ROOT/STM32/firmware/Debug"
LOG_FILE="$REPO_ROOT/STM32/build.log"
ADDRESSES_JSON="$REPO_ROOT/addresses.json"
ADDRESSES_H="$REPO_ROOT/STM32/firmware/Core/Inc/addresses.h"

# Staleness check only -- deliberately does NOT run generate_addresses.py
# itself. That script also writes raspi/control/linaddresses.py,
# currentsensor/firmware/addresses.h, and addresses.md -- files well
# outside STM32/, which a "just build the firmware" script shouldn't
# silently touch as a side effect. See root CLAUDE.md's LIN Protocol
# "Address Table Single Source of Truth" section for why regeneration
# stays a deliberate, separate step. Hit live 2026-09-07: addresses.json
# was edited but the generator never re-run, so this build would have
# silently compiled a stale addresses.h.
if [ -f "$ADDRESSES_JSON" ] && [ -f "$ADDRESSES_H" ] && [ "$ADDRESSES_JSON" -nt "$ADDRESSES_H" ]; then
  echo "ERROR: addresses.json is newer than $ADDRESSES_H"
  echo "Run 'python generate_addresses.py' from the repo root first, then build again."
  exit 1
fi

# Bundled inside the STM32CubeIDE install — adjust if the IDE version
# changes (these paths are version-specific).
GCC_BIN="/c/ST/STM32CubeIDE_1.19.0/STM32CubeIDE/plugins/com.st.stm32cube.ide.mcu.externaltools.gnu-tools-for-stm32.13.3.rel1.win32_1.0.0.202411081344/tools/bin"
MAKE_EXE="/c/Users/rembo/Documents/make-3.81/bin/make.exe"

export PATH="$GCC_BIN:$PATH"

cd "$BUILD_DIR"

: > "$LOG_FILE"

set +e
{
  "$MAKE_EXE" clean
  "$MAKE_EXE" -j4 all
} 2>&1 | while IFS= read -r line; do
  echo "$line"
  echo "$line" >> "$LOG_FILE"
done
BUILD_STATUS=${PIPESTATUS[0]}
set -e

if [ "$BUILD_STATUS" -ne 0 ]; then
  echo
  echo "Build FAILED (exit $BUILD_STATUS) — see above, also saved to $LOG_FILE"
  exit "$BUILD_STATUS"
fi

echo
echo "Built: $BUILD_DIR/demoboard.elf"
ls -la "$BUILD_DIR/demoboard.elf"
