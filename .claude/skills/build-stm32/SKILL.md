---
name: build-stm32
description: Headless clean-build of the STM32 firmware (STM32/firmware/), no STM32CubeIDE GUI needed. Use when the user asks to build, compile, or rebuild the STM32 firmware.
---

Run `STM32/build.sh` from the repo root. It cleans and rebuilds
`STM32/firmware/` using the GCC/make toolchain bundled inside the
existing STM32CubeIDE install (no separate toolchain, no IDE GUI).
Output: `STM32/firmware/Debug/demoboard.elf`.

This only compiles — it never flashes or touches the STM32 controller.
Flashing (`STM32_Programmer_CLI`) is a separate, not-yet-built step that
needs the user's explicit, in-the-moment consent every time, same as
any motor command — see `raspi/CLAUDE.md`'s Motor Execution Consent
section (applies here too, not just the Raspi side). Don't let
"build" imply "and now flash it."

If the STM32CubeIDE version changes, the hardcoded toolchain paths in
`STM32/build.sh` (`GCC_BIN`) will need updating — see `STM32/CLAUDE.md`'s
Build & Flash section for how they were found.
