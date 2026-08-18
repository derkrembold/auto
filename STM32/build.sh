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
