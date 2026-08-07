#!/bin/bash
# Headless flash of the built STM32 firmware via STM32_Programmer_CLI —
# no STM32CubeIDE GUI needed. Uses the CubeProgrammer bundled inside the
# existing STM32CubeIDE install (same pattern as build.sh).
#
# IMPORTANT — this writes firmware that starts running immediately, and
# --reset additionally starts it running right after write. Both require
# the user's explicit, in-the-moment consent every single time, same as
# any motor command — see raspi/CLAUDE.md's Motor Execution Consent
# section (applies here too, not just the Raspi side). This script does
# not and cannot enforce that itself — it's on whoever/whatever invokes
# it (Claude) to ask first, every time, no exceptions, no assuming
# permission from an earlier approval.
#
# Usage: flash.sh [path/to/firmware.elf] [--reset]
#   Default firmware path: STM32/firmware/Debug/BringUpBoard.elf
#   --reset: also reset+run the target right after flashing (-rst).
#            Omitted by default — without it, the target sits halted
#            after flashing until reset manually (button/power-cycle) or
#            via a separate, explicitly-consented run of this script.
#
# Every invocation (by Claude or run manually) appends one line to
# STM32/flash.log — timestamp, firmware path, mode, exit status. Lets
# Claude check when a flash last happened without having to ask, even
# for flashes it didn't itself trigger. Gitignored, not a build artifact.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="$REPO_ROOT/STM32/flash.log"

PROGRAMMER_CLI="/c/ST/STM32CubeIDE_1.19.0/STM32CubeIDE/plugins/com.st.stm32cube.ide.mcu.externaltools.cubeprogrammer.win32_2.2.200.202503041107/tools/bin/STM32_Programmer_CLI.exe"

FW_PATH="$REPO_ROOT/STM32/firmware/Debug/demoboard.elf"
DO_RESET=0

for arg in "$@"; do
    case "$arg" in
        --reset)
            DO_RESET=1
            ;;
        *)
            FW_PATH="$arg"
            ;;
    esac
done

log_result() {
    local status=$?
    local mode="write+verify"
    [ "$DO_RESET" -eq 1 ] && mode="write+verify+reset"
    echo "$(date '+%Y-%m-%d %H:%M:%S')  $mode  $FW_PATH  exit=$status" >> "$LOG_FILE"
}
trap log_result EXIT

if [ ! -f "$FW_PATH" ]; then
    echo "Firmware not found: $FW_PATH" >&2
    echo "Build it first (STM32/build.sh / /build-stm32)." >&2
    exit 1
fi

ARGS=(-c port=SWD -w "$FW_PATH" -v)
if [ "$DO_RESET" -eq 1 ]; then
    ARGS+=(-rst)
fi

"$PROGRAMMER_CLI" "${ARGS[@]}"
