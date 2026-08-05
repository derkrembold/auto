# STM32 — Context for Claude Code

This folder holds the BLDC motor control firmware and its build/flash
automation. Structured like the root `CLAUDE.md` (Concept/Architecture)
so it stays easy to split further if it grows.

# Concept

The "why" — rarely changes.

## Goal

Runs the BLDC motor control algorithm that the whole project's
optimization loop tunes. A new parameter set (see root `CLAUDE.md`'s
Goal) gets applied by building and flashing new firmware — that's the
"apply parameters" step of each optimization iteration.

# Architecture

The "how" — evolves as the firmware and tooling get built out.

## Build & Flash

- Both STM32CubeIDE and `STM32_Programmer_CLI` are installed on the
  Windows host (the "STM32 host" machine in the root `CLAUDE.md` — this
  machine, not the STM32 controller being flashed).
- **Headless build: done (2026-08-04).** `STM32/firmware/` holds the
  actual project, copied read-only from the live STM32CubeIDE workspace
  project at `C:\Users\rembo\STM32CubeIDE\workspace_1.19.0\demoboard`
  (source left untouched — that directory is read-only from this repo's
  perspective, same as the KiCad directory below).
  **Correction (2026-08-04, same day):** initially copied from
  `C:\Users\rembo\Documents\STM32\BringupBoard.zip_expanded\BringUpBoard`
  instead (per the user's own initial pointer) — that turned out to be a
  stale/simpler snapshot (no PI controller, no ramping, older `main.c`
  dated April vs. the real project's June) of what's actually an
  actively-developed different project. Caught when comparing button/LED
  GPIOs against the KiCad schematic led to noticing `main.c` didn't match
  what `STM32/notes.md` already documented (PI controller etc.). Fully
  re-copied from the correct source; the wrong copy's build/flash output
  earlier that day should be treated as based on stale firmware, not
  representative of the current project. STM32CubeIDE already auto-
  generates a normal GNU Make
  build (`firmware/Debug/makefile` etc.) — that's literally what the IDE
  itself invokes internally on "Build." Both `arm-none-eabi-gcc` and
  `make` are bundled inside the STM32CubeIDE install itself, no separate
  toolchain download needed:
  - GCC: `C:\ST\STM32CubeIDE_1.19.0\STM32CubeIDE\plugins\com.st.stm32cube.ide.mcu.externaltools.gnu-tools-for-stm32.13.3.rel1.win32_1.0.0.202411081344\tools\bin\arm-none-eabi-gcc.exe`
  - `STM32_Programmer_CLI`: `...cubeprogrammer.win32_2.2.200.202503041107\tools\bin\STM32_Programmer_CLI.exe`
  - `make`: also bundled in a sibling plugin dir, though `C:\Users\rembo\Documents\make-3.81\bin\make.exe` (a separate, older GNU Make 3.81) works fine too and is what `build.sh` actually uses.
  `STM32/build.sh` wraps this (sets `PATH`, `make clean` then `make -j4
  all` in `firmware/Debug/` — always cleans first, the build is fast
  enough that this costs little and removes stale-object bugs as a
  failure class entirely) — run it (or the `/build-stm32` skill, a thin
  wrapper around it) instead of re-deriving the paths each time.
- **Fixed while copying (both times):** `firmware/Debug/makefile` had
  the linker script path hardcoded to the *original* project's absolute
  location (`-T"C:\Users\rembo\STM32CubeIDE\workspace_1.19.0\...\
  STM32H743VGTX_FLASH.ld"`) — copied verbatim by STM32CubeIDE's
  generator, so the copy's build only worked by coincidence (reading the
  original's linker script, right up until the original changes or
  moves). Changed to a relative path (`../STM32H743VGTX_FLASH.ld`) so
  the copy is genuinely standalone. This is a generic STM32CubeIDE
  behavior, not specific to one project — expect to redo this same
  one-line fix if the firmware is ever re-copied from source again
  (e.g. after further upstream changes). Current build output (from the
  correct `demoboard` source): `demoboard.elf`, 47208/16/2016
  text/data/bss — larger than the earlier wrong-source build
  (42384/16/1848), consistent with the extra PI-controller/ramping code
  the correct source actually has.
- **Headless flash: done (2026-08-04).** `STM32_Programmer_CLI` is the
  tool (separate from the IDE GUI). Connectivity was confirmed first
  (read-only connect, `-c port=SWD`, nothing written), correctly
  identifying the real target: Device ID `0x450` (STM32H74x/75x family),
  `STM32H7xx`, 1MB flash, Cortex-M7 — matches the STM32H743VGT6. Two
  harmless quirks in that output, both explained, not bugs:
  - `Board: NUCLEO-F401RE` — the ST-Link probe is physically cut from a
    NUCLEO-F401RE board and used standalone (already worked fine this
    way with STM32CubeIDE). This is stale identification baked into the
    probe itself, unrelated to the actual connected target.
  - `Voltage: 0.01V` even while communication works — the VTref/5V
    sense line from the target board to the ST-Link isn't wired (no
    cable for it), so the tool can't measure real target voltage.
    SWDIO/SWCLK/GND are enough for SWD communication to work regardless;
    this reading just can't be trusted as "target is unpowered."
  With explicit, in-the-moment consent, an actual write+verify then
  succeeded (41.41 KB, "Download verified successfully"), without
  `-rst` — the target sat halted afterward rather than immediately
  running, reset triggered manually (SW2) instead. That first flash was
  from the wrong-source build (see Headless build above).
  **Reflashed (2026-08-04) with the corrected `demoboard`-sourced
  build** (46.12 KB, verified) via `/build-stm32` + `/flash-stm32`, both
  with explicit consent. Confirmed working on real hardware after a
  manual reset (SW2) — **motor runs correctly** on the corrected
  firmware.
  `STM32/flash.sh` (and the `/flash-stm32` skill, a thin wrapper around
  it) wraps the connect/write/verify invocation — but wraps the
  *mechanics* only. Both writing firmware and resetting the target start
  code running on real hardware that can move the motor, so both still
  need the same explicit, in-the-moment consent as motor commands do
  (see `raspi/CLAUDE.md`'s Motor Execution Consent section; the rule
  applies to anything that can move the motor, not just the Raspi side)
  — every time, regardless of earlier approvals, and the script cannot
  enforce this itself. `--reset` (`-rst`, immediate run after flashing)
  defaults off and is its own separate consent event, distinct from the
  write itself.

## LIN Slave

- The STM32 controller is the LIN slave; the Raspi is the LIN master.
  See the root `CLAUDE.md`'s LIN Protocol section for the shared
  wire-level protocol (header requirement, echo-compare, etc.).
- The address/PID table equivalent to the Raspi's `linaddresses.py` is
  `addresses.h` here. Both tables must stay in sync — the address itself
  commits to a read/write direction that both ends have to agree on.

## Motor Control & Trigger Pin

- Drives the BLDC motor based on LIN commands from the Raspi (currently
  just `speed`, 0 = stop).
- The 3 Hall sensor signals are used here for commutation as normal:
  the Saleae only taps them non-invasively, no firmware change needed
  for that.
- A free GPIO pin must be set high in the same code path that starts the
  motor, and low again on stop — this is the hardware trigger for the
  Saleae capture start (see root `CLAUDE.md` Data Flow, and
  `saleae/CLAUDE.md`).

## Buttons / Switches

Physical designators are from the KiCad schematic/PCB, a project that's
**also** (confusingly) named `demoboard` — but a different, separate
`demoboard` from the STM32CubeIDE firmware project this folder is
sourced from (see Build & Flash above): the PCB one lives at
`C:\Users\rembo\Documents\KiCad\designs\demoboard\demoboard`, external
to this repo, read-only, not to be confused with the firmware source at
`C:\Users\rembo\STM32CubeIDE\workspace_1.19.0\demoboard`. Traced via the
PCB netlist (`Net-(U1-<pin>)` pad nets), not just the `.ioc`/`main.c`
naming, since the STM32CubeIDE project carries no SW-designator labels
of its own.

- **SW1** → PE5. **SW3** → PC5. Both currently just toggle an onboard
  LED while held (bring-up/test code, `main.c:207-218` for SW1/PE5→PB7,
  `main.c:223-234` for SW3/PC5→PB8) — this is not necessarily their
  final purpose, don't assume it stays this way.
- **SW2** → `NRST` (confirmed via PCB net). The board's hardware reset
  button — not a GPIO, not read by firmware.
- **SW4** → reset button for the MCP2003B-E/SN chip (the LIN
  transceiver on this board). Not currently referenced in `main.c`.

## Instance-Selection Jumper (PB14/PB15)

Hardware strap pins for the multi-instance LIN addressing scheme — see
root `CLAUDE.md`'s LIN Protocol "Address Table Single Source of Truth"
section for the full design (why this exists: byte-identical firmware
across multiple physical motor boards, instance number read at runtime
instead of baked into the firmware source).

- **`PB14`/`PB15`**, configured `GPIO_MODE_INPUT` + `GPIO_PULLUP`
  (`main.c:724-728`). Jumper to GND to select — reads `GPIO_PIN_RESET`
  when jumpered, floating/pulled-up otherwise.
- Wired to connector **`J1`** (`Connector_Generic:Conn_02x05_Top_Bottom`
  in the KiCad schematic — see Buttons/Switches above for the read-only
  KiCad path): `PB14` → `J1` pin 7, `PB15` → `J1` pin 5. Both nets are
  direct/exclusive (just the MCU pad and the header pad, no other
  component) with GND on the adjacent pins each way (pin 5 between GND
  pins 4/6, pin 7 between GND pins 6/8) — a plain 2-pin jumper cap
  bridges signal to GND directly.
- `Conn_02x05_Top_Bottom` numbers **column-wise, not left-to-right**
  (row 1 = pins 1,3,5,7,9; row 2 = pins 2,4,6,8,10) — easy to jumper the
  wrong physical pin if you assume sequential numbering. Worth a
  multimeter continuity check if the jumper doesn't seem to do anything.
- **Confirmed working end-to-end (2026-08-05)**, wiring and firmware
  logic verified correct against the KiCad schematic and via LED test
  (`main.c:293-323`: reads `PB14`/`PB15`, drives `PB8`/`PB7`
  accordingly). Root-caused an initial "doesn't do anything" failure to
  **two cold solder joints on `J1`** — see `STM32/notes.md`'s
  Fehlerliste, Issue #2. Not a firmware or schematic problem.
- **Not yet done:** the actual LIN dispatch logic in `main.c` doesn't
  read these pins or compute `base_pid | instance_id` yet — only the
  raw pin-read-drives-LED test exists so far. See root `CLAUDE.md`'s
  Open Points for this as a concrete remaining step.

## Hardware

- **MCU:** STM32H743VGT6.
- **Hall sensor GPIOs:** PC0, PC1, PC2.
- **MOSFET GPIOs:** PE8–PE13 (6 pins = 3 half-bridges, standard 3-phase
  BLDC bridge topology).
- Datasheets for the MCU and the MOSFET half-bridge driver (IR2101) are
  in `STM32/datasheets/`. The MCU datasheet is a full reference manual
  (~7MB) — don't load it into context wholesale, read specific pages
  only when a specific detail is needed.
- Note: the datasheet on file is `STM32H743BI_DB-EN.pdf` (BI variant),
  but the actual part is VGT6 — same family, exact variant differs
  (package/flash size). Unconfirmed whether this matters for anything
  used so far.

## Commutation & Control

- 6-step trapezoidal commutation. Main loop calls `driveStep(speedglobal,
  dirglobal)`, which reads the 3 Hall GPIOs (6 position states via Gray
  code) and calls `driveState(speed, st)` with the next state.
- `driveState()` switches the 6 MOSFETs: briefly charges the bootstrap
  capacitor, then drives the phase pair for a duration proportional to
  `speed` (`speed * 5`, so max `speed` is 255) within a fixed ~1275µs +
  10µs cycle.
- A PI controller (`picontrol()`, setpoint/processvalue → control
  variable, with anti-windup) sits on top of this for closed-loop speed
  control.
- Full state tables (CW/CCW), the `driveState()`/`driveStep()`
  description, the PI controller source, measured RPM-vs-control-value
  and oscilloscope timing tables, and the STM32CubeIDE project's file
  tree are in `STM32/notes.md` (German, kept as originally written).
  **`STM32/notes.md` is a living document** — not a frozen snapshot, keep
  it updated as the firmware changes (including its "STM32CubeIDE
  Projektstruktur" section, which will need to change or go away
  entirely if the standalone-build goal below is achieved).

## RPM Measurement Resolution

**`rpm` is quantized in steps of 25 — this is a real resolution limit
of the measurement, not noise.** In `main.c`:
```c
// RPMFACTOR: 60*speedcount/(24*0.1); 60sec/min; 24steps/Umdrehung; 0.1s==100ms;
const uint16_t RPMFACTOR = 25;
const uint16_t SAMPLERATE = 100; // in ms
...
rpm = RPMFACTOR*hallCounter;
```
`hallCounter` is an integer Hall-edge count accumulated over a fixed
100ms window, so `rpm` can only ever come out as a multiple of 25.
Confirmed empirically (2026-08-04): every `rpm` value from the
`validate_speed.py` run (see root `CLAUDE.md`'s Open Points) was an
exact multiple of 25, and the run's observed `speed`-vs-`rpm` deviation
(~±6%) is almost fully explained by this quantization (25/400 ≈ 6.25%)
rather than by `speed` and `rpm` actually meaning different things.

**This is entirely a property of the current `main.c` — `RPMFACTOR`,
`SAMPLERATE`, and the 24-steps/revolution assumption could all change
if the firmware changes.** Don't treat "25" as a fixed constant of the
hardware; re-check this section against `main.c` if the firmware is
ever rebuilt from a different/updated source. Relevant for the future
optimization loop's cost function: don't mistake this quantization step
for measurement noise when scoring control quality.

## Known Hardware Issue

The current-sense shunt (on one MOSFET pair, used to measure phase
current) blew (measured 600Ω instead of its rated value) and was bridged
with a copper wire as a fix. **Current sensing is therefore currently
physically disabled on this board** — any current-based safety cutoff
is not possible right now, only time/speed-based limits are. See
`STM32/notes.md` ("Fehlerliste").

The motor currently runs at 24V (not its 36V rating); the supply
transformer has its own current limiting, and saturation-like behavior
has been observed above a certain control value — possibly that supply
limit, not the motor or firmware. See `STM32/notes.md`
("Betriebsbedingungen"). Switching to battery power (see root
`CLAUDE.md`'s Battery section) removes this implicit current limiting.

## Stall Detection (Planned, Deprioritized)

**Not the current primary approach — see `raspi/watchdog/CLAUDE.md`'s
two-layer LIN-based check (lower layer `rpm`, upper layer current
sensor: stall = current flowing while `rpm` reads 0) for what's actually
planned first.** This STM32-local approach is kept as a real future
plan, not discarded, but deliberately sequenced *after* the standalone
(non-STM32CubeIDE) build/flash environment goal above — touching this
firmware is much more practical once that tooling friction is gone.
Revisit then, not before.

Idea, for when that time comes: detect a locked/stalled rotor from the
Hall signals the firmware already reads every commutation step
(~785×/sec) — if the motor is commanded to move but no Hall transition
occurs within some timeout, cut the MOSFETs. A stall is the most
dangerous current-sensing-gap scenario (no back-EMF, only 65mΩ phase
resistance, so stall current can be large and sustained) and is
plausibly what caused the blown shunt in the first place (see
`STM32/notes.md` "Fehlerliste" Issue #1 — symptom was "won't start
turning until the shaft is moved," which reads like a stall).

This would run locally on the STM32 (no LIN round-trip), reacting in
single-digit milliseconds — faster than the LIN-based watchdog check,
which polls roughly 1×/second and is correspondingly slower to react.
That speed difference is exactly why this remains a real future
enhancement rather than something to discard, even though it's not
being built next.

Not yet implemented — see Open Points below.

## Status

Imported (2026-08-04) — see Build & Flash above for the source, the
same-day wrong-source correction, and current build/flash state.
`STM32/notes.md`'s file-tree section describes the STM32CubeIDE project
structure in general; it predates the actual import and hasn't been
re-verified against the corrected `demoboard` source specifically.


## Motor Information
Produktinformationen "BLDC-Motor 1000W, Bosch, 1.607.022.68B, 36 V-, 35 A -brushless"
BLDC-Motor, Bosch, 36V-/16A 1000W
Laufruhiger doppelt kugelgelagerter Brushless-Motor für den Betrieb über einen Drehzahlregler bzw. über ein Steuergerät für Brushless Motoren z.B. für e-Bikes oder über einen Fahrtregler z.B. aus dem Modelbaubereich. Der Motor ist baugleich mit dem F016L68035 er verfügt aber zusätzlich über drei Hallsensoren und einen Temperatursensor. Durch das größere Alugehäuse ist er bis 1000W belastbar.

Durch die starken Permanentmagnete des Rotors auch sehr gut als Drehstromgenerator für Windräder o.ä. einsetzbar.

Technische Daten:

Betriebsspannung: bis 36 V-
Stromaufnahme bei Maximalleistung: 35 A
Leistung: max. 1,0 kW
Drehmoment: 2,6 Nm
Lastdrehzahl: 3650 U/min bei 36V
ca. 105kV
Widerstand U-V/V-W/U-W: 65 mOhm
Lager: Kugellager
Wellen-Innengewinde: M10x1,25
Motormaße ohne Welle (ØxL): ca. 230x95 mm
Wellenmaße (LxØ): ca. 55x22 vorne: 20 mm
Leerlauf-Drehzahl: (ca. 105 RPM/V) = 5V: 580 U/min, 9V: 1040 U/min, 12V: 1380U/min, 16V: 1800 U/min, 24V: 2700 U/min, 36V: 4050 U/min, 48V: 5400 U/min
Leerlauf Stromverbrauch: bei 5V: ca.: 0,5A,  bei 48V ca.: 1,4A


## Open Points (STM32-specific)

- `STM32/notes.md`'s file-tree section needs re-verification against the
  corrected `demoboard` source — written before the import, may not
  match exactly.
- Exact trigger-pin GPIO assignment.
- Implement Hall-based stall detection (see Stall Detection section
  above) — deprioritized, was sequenced after the standalone-build-
  environment goal; both build and flash are now headless, so this can
  be reconsidered/picked up next. When it happens: timeout/threshold not
  yet chosen, needs tuning against real startup behavior (torque needed
  to overcome static friction before the first Hall transition must not
  trigger a false stall trip).

Fill these in here once fixed, not in the root `CLAUDE.md`.
