---
name: flash-stm32
description: Headless flash of built STM32 firmware to the real controller via STM32_Programmer_CLI, no STM32CubeIDE GUI needed. Use when the user asks to flash, program, or download firmware to the STM32.
---

Run `STM32/flash.sh [path/to/firmware.elf] [--reset]` from the repo
root. It connects over SWD (via the ST-Link) and writes+verifies the
given `.elf` (default: `STM32/firmware/Debug/demoboard.elf`, i.e.
whatever `/build-stm32` last produced) using the `STM32_Programmer_CLI`
bundled inside the existing STM32CubeIDE install.

**Hard requirement — do not skip:** both writing firmware and resetting
the target start code running on real hardware that can move the motor.
Ask the user for explicit, in-the-moment consent immediately before
running this script — every single time, even if they already agreed to
a flash or a reset earlier in the same conversation. Earlier approval
does not carry forward. See `raspi/CLAUDE.md`'s Motor Execution Consent
section (applies here too, not just the Raspi side).

- Without `--reset` (default): writes+verifies only. The target sits
  halted afterward — the user resets it manually (SW2, or power-cycle)
  when ready, on their own schedule.
- With `--reset`: also resets+runs the target immediately after
  flashing (`-rst`). This is a *separate* consent event from the write
  itself — ask for it specifically, don't fold it into "can I flash?".
  Default behavior (no `--reset`) is preferred unless the user asks for
  the immediate-run behavior.

If the STM32CubeIDE version changes, the hardcoded `PROGRAMMER_CLI` path
in `STM32/flash.sh` will need updating — see `STM32/CLAUDE.md`'s Build &
Flash section for how it was found.
