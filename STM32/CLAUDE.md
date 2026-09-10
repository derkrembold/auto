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
    this reading just can't be trusted as "target is unpowered." **Don't
    read a failed connect + `0.01V` as confirmation the board has no
    power** — that reading is always ~0V here, powered or not, so it's
    not diagnostic either way (a mistake made live 2026-08-12, see next
    bullet).
  - **`Error: Unable to get core ID` / `No STM32 target found`**
    (first hit 2026-08-12): a real SWD-level connection failure, not a
    power problem (see the `0.01V` point above — that reading doesn't
    move regardless). Four consecutive `flash.sh` attempts failed this
    way; power-cycling the target board (unplug/replug its supply)
    between attempts 4 and 5 fixed it — the 5th attempt succeeded
    (`flash.log`, 2026-08-12 13:24:29). Plausible mechanism: the
    power-cycle reset the target's own debug port state, not that it
    was ever actually unpowered. Not yet a confirmed root cause, just
    the one troubleshooting step observed to work so far — if this
    recurs, try the power-cycle first before assuming a cabling fault.
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
- **Trigger pin chosen and confirmed working end-to-end (2026-08-17):**
  `GPIO_PIN_12`/`GPIOB`, accessible off connector `J1`, repurposed from
  an old debug/heartbeat toggle (`HAL_GPIO_TogglePin`, once per
  RPM-sampling window — removed). Set HIGH on the `cntl3mot` dispatch
  transition to nonzero `controlvariableinput`, LOW back to `0`
  (`main.c:352-358`) — mirrors `raspi/watchdog/watchdog.py`'s
  `speed_became_nonzero_at` semantics, so "test running" means the same
  thing on both ends.
  - **Bug found and fixed the same day:** a leftover SW1-button test
    block (`main.c:262-279`, added earlier in the session to verify the
    Saleae channel mapping) also wrote `GPIO_PIN_12` — unconditionally,
    on *every* pass through the tight `while (bodyrecvd == false)`
    polling loop (thousands of times/sec), not just on a button edge.
    Since SW1 isn't pressed during a real motor run, this continuously
    forced the pin back to `GPIO_PIN_RESET` immediately after the real
    `cntl3mot` handler set it HIGH — the two writes were fighting every
    loop iteration. Symptom matched exactly: Saleae showed only a
    ~14µs blip instead of a sustained HIGH, and a multimeter read a
    steady 0V throughout an entire real motor run (while confirming a
    clean 3.3V from the same pin via the SW1 button test alone, static/
    motor-stopped — proving the pin and wiring were fine, only the
    *logic* was wrong). Root-caused by reading `main.c` directly rather
    than further hardware probing, once the LIN write log had already
    ruled out an extra/unexpected command as the cause. Fix: removed
    the two `GPIO_PIN_12` lines from the SW1 block, leaving its
    `GPIO_PIN_8` LED behavior untouched.
  - **Confirmed against real hardware (2026-08-17)**, after
    build+flash: a 20s real Saleae capture (`saleae/exports/
    step_response_trigger_test4/`, real `LOGIC_PRO_16` device, not
    simulation) during a live `capture_step_response.py` run shows
    channel 3 HIGH continuously from t=4.035s to t=11.846s (7.811s, no
    flicker) — matches the expected ~7.8s step-response window exactly,
    LOW before and after. The trigger pin is now usable as a real
    Saleae hardware capture trigger.

## Buttons / Switches

Physical designators are from the KiCad schematic/PCB, a project that's
**also** (confusingly) named `demoboard` — but a different, separate
`demoboard` from the STM32CubeIDE firmware project this folder is
sourced from (see Build & Flash above). **Correction (2026-08-17): the
current, correct KiCad project is `demoboardV2`, not the plain
`demoboard` this section used to reference throughout** — there are two
separate KiCad projects on disk,
`C:\Users\rembo\Documents\KiCad\designs\demoboard\demoboard` (older,
schematic last touched 2025-09-21) and
`C:\Users\rembo\Documents\KiCad\designs\demoboardV2\demoboardV2`
(current, schematic last touched 2026-03-25) — both external to this
repo, read-only. Not to be confused with the firmware source at
`C:\Users\rembo\STM32CubeIDE\workspace_1.19.0\demoboard` (a third,
unrelated thing sharing the same base name). Traced via the PCB netlist
(`Net-(U1-<pin>)` pad nets), not just the `.ioc`/`main.c` naming, since
the STM32CubeIDE project carries no SW-designator labels of its own.

**Open question this correction raises, not yet resolved:** the
pin-mapping facts below (SW1-4, and the `PB14`/`PB15`↔`J1` mapping in
the next section) were documented as "confirmed via the KiCad
schematic," but the path written down at the time was the plain
`demoboard` one — meaning it's not certain whether the *verification
itself* actually used `demoboardV2` (in which case these facts are
still fine, just mis-labeled) or genuinely used the older, superseded
schematic (in which case they'd need re-checking against `demoboardV2`
before being trusted further, e.g. before wiring anything new off `J1`
or `J2`). Re-verify against `demoboardV2` specifically before relying on
these for new hardware work.

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
- **Hall sensor GPIOs:** PC0, PC1, PC2. **Confirmed against `demoboardV2`'s
  PCB netlist (2026-08-17)**, not just inferred from `main.c`: `U1`
  (the `LQFP-100` MCU footprint) pad 15 = `PC0` = net **"H1"**, pad 16 =
  `PC1` = net **"H2"**, pad 17 = `PC2_C` (KiCad's symbol-library name for
  `PC2` on this STM32H7 part — it has a dual-ADC-input `_C` alternate)
  = net **"H3"**. So the board's `H1`/`H2`/`H3` silkscreen/net labels
  (routed out to connector `J2`, see `saleae/CLAUDE.md`) map 1:1 to
  `PC0`/`PC1`/`PC2` in that order — confirms these are the same signals
  the Saleae can safely tap non-invasively off `J2` for speed
  measurement, per root `CLAUDE.md`'s Data Flow section.
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
- **`KP`/`KI` settable live over LIN (2026-08-18), replacing the old
  on/off status-LED toggle on the same `cntl0mot` PID.** `main.c`
  declares `const float KPDEFAULT = 0.15f;`/`KIDEFAULT = 0.4f;` and
  mutable `float KP = KPDEFAULT;`/`KI = KIDEFAULT;`; the `cntl0mot`
  dispatch does `KP = KPDEFAULT + (int8_t)rx_body[0]/100.0;` and the
  same for `KI`/`rx_body[1]` (both under the existing `checksum_ok`
  gate). **Deliberately absolute-from-default, not cumulative** — each
  message recomputes from `KPDEFAULT`/`KIDEFAULT` fresh, it does not
  add to whatever `KP`/`KI` currently is. This was a real live
  correction during design: an initial `KP += ...`/`KI += ...`
  implementation drifted with repeated calls (needing external state
  tracking to reach a target value); switched to `KP =
  KPDEFAULT + delta` specifically so the firmware side stays stateless
  and a Python-side grid/gradient search never needs to track prior
  applied values, just `delta = target - default` per point. See root
  `CLAUDE.md`'s Goal and `raspi/CLAUDE.md`'s `pi` command entry (the
  Raspi-side interface — floats in real `KP`/`KI` units, not raw wire
  bytes) for the intended optimization-loop use. A signed-byte wire
  encoding at ×100 scale means each gain's delta range is `-1.28`..
  `1.27` (chosen over a ×1000 scale specifically for range over
  precision — ×1000 would only reach `default ± 0.128`, too narrow
  for a real grid search given `KP`/`KI`'s current small magnitude).
  **Not yet done:** a firmware-side sanity clamp on
  the resulting `KP`/`KI` (nothing currently stops an automated search
  loop from driving either gain into an unstable region), and no
  status readback of the currently-applied values exists yet.

  **Confirmed on real hardware (2026-08-19),** flashed and deployed the
  same day: a `runs/2026-08-19_logs/` capture (fetched via
  `/analyze-logs`, no anomalies) shows the user manually boundary-
  testing all four ±0.01 single-gain deltas, each followed by a short
  `speed 500`→`speed 0` pulse — `cntl0mot [0x01,0x00]` (KP→0.16),
  `[0xff,0x00]` (KP→0.14), `[0x00,0x01]` (KI→0.41), `[0x00,0xff]`
  (KI→0.39). No checksum errors, no bus-hang, no unexpected `st3mot`
  counter movement — the checksum-gated dispatch handled all four
  cleanly. Only WARNINGs in that log were expected/benign: one idle-
  timeout stop (a pause between test steps) and five observe-only
  current-based stall signatures, plausibly just the ~3s speed pulses
  being too short for the motor to finish spinning up, not a real
  stall (see `raspi/watchdog/CLAUDE.md`'s Two-Layer Safety Check for
  why that layer doesn't act on its own yet).

- **`updateramp()` gained an `enabled` toggle (2026-08-20), deliberately
  disabled for step-response characterization.** Was `void
  updateramp(void)`, unconditionally advancing `controlvariable` toward
  `controlvariableinput` by `RAMPSTEP` per call every main-loop
  iteration (soft-start/soft-change behavior). Now `void
  updateramp(bool enabled)`: `true` keeps the original `RAMPSTEP`-limited
  ramp, `false` jumps `controlvariable = controlvariableinput` directly
  — a true step, no smoothing. The only call site (`main.c`'s main loop)
  currently passes `false` unconditionally, so ramping is off for *all*
  speed changes right now, not just during step-response runs — there's
  no separate "characterization mode" vs. "normal operation" distinction
  yet. Deliberate, not an oversight: a software ramp on the setpoint
  acts as an input prefilter, which distorts exactly what a step-response
  characterization run is trying to measure (rise time, overshoot) —
  agreed after review. Planned: flip back to `updateramp(true)` once the
  grid search and gradient search (see root `CLAUDE.md`'s Goal) have
  found the optimal `KP`/`KI`, restoring smooth setpoint changes for
  normal/production operation.
  - **Caution while it stays disabled:** current sensing is still
    physically disabled (see Known Hardware Issue below), and an
    un-ramped jump straight to a large `controlvariableinput` is exactly
    the kind of event most likely to produce a large current spike —
    the same failure class suspected of blowing the original current-
    sense shunt (see Known Hardware Issue below). Worth keeping in mind
    at higher target speeds/currents during grid-search sweeps.
  - **Confirmed on real hardware the same day (2026-08-20,
    `runs/2026-08-20_134718_experiment/`, `pi 0.0 0.0` i.e. default
    gains): most of the previously-observed step-response "dead time"
    was a ramp artifact, not a real property of the motor/controller.**
    With the ramp disabled, `rpm` (both LIN `st2mot` and independent
    Saleae Hall-edge ground truth) reaches ~875 (~88% of the 1000
    target) within ~0.3s of the step, then oscillates/overshoots in a
    ~950–1050 band before settling — a fast, visibly real step response.
    Earlier ramp-enabled runs' apparent lag was mostly the
    `RAMPSTEP`-limited setpoint itself taking time to reach the target,
    not slow physical/control-loop dynamics. Relevant for the future
    grid/gradient search's cost function (see `analysis/CLAUDE.md`'s
    Open Points): any dead-time-like metric should be computed from
    ramp-disabled runs, since the ramp-enabled number was inflated by
    this artifact.
- Full state tables (CW/CCW), the `driveState()`/`driveStep()`
  description, the PI controller source, measured RPM-vs-control-value
  and oscilloscope timing tables, and the STM32CubeIDE project's file
  tree are in `STM32/notes.md` (German, kept as originally written).
  **`STM32/notes.md` is a living document** — not a frozen snapshot, keep
  it updated as the firmware changes (including its "STM32CubeIDE
  Projektstruktur" section, which will need to change or go away
  entirely if the standalone-build goal below is achieved).

## Planned Redesign: Pulse/Reset/Status Protocol + Kickstart Algorithm

**Everything in this section is planned, not built — captured
2026-09-07 from the user's own design draft (originally a standalone
`BLDC_System_Specification.md`, folded into this file and deleted the
same day — see git history for the original wording). Subject to
change; the actual redesign happens interactively between the user and
Claude Code as it's built, not by following this plan mechanically.**
This redesigns/extends the currently-*built* kickstart mechanism
(`driveKickStart()`/`driveStepKickStart()`, `KICKSTART_SPEED`,
`stuckwindowcount` — see `analysis/grid_search_log.md`'s 2026-08-27/28
sections for its full build history, real-hardware confirmation, and
the two real gaps already found there) — this section is **not** yet
reflected as "built" state anywhere else in this file, only in that
chronological log.

**Planned LIN command changes:**
- `pulse` (Pi → STM32): currently a single raw open-loop `driveStep()`
  pulse (`cntl1mot`, built 2026-08-28 for Hall-position
  characterization — see `raspi/control/characterize_hall_positions.py`
  and `linbus.set_pulse()`). Planned: the firmware-side handler fires a
  **3-pulse sequence** (previous state n-1, current state n, next
  state n+1) automatically per `pulse` command, not a single directional
  pulse — see the Kickstart Algorithm entry below for why (hedges
  against Hall-sensor chattering at sector boundaries, see the "Hall
  Chattering" caveat below). Needs reconciling with the existing
  single-pulse `cntl1mot` infrastructure before implementation — not
  yet decided whether the 3-pulse behavior replaces the single-pulse
  one outright or the two coexist as different commands.
- `reset` (Pi → STM32, new, separate command): resets `integral`,
  `kickstartCounter`, `timeoutCounter`, `checksumCounter`, `errorCode`.
  Not yet assigned a PID in `addresses.json` — needs one before
  implementation (see root `CLAUDE.md`'s LIN Protocol section for the
  single-source-of-truth address process).
  `raspi/watchdog/watchdog.py` needs a corresponding verb.
- `status` (STM32 → Pi, 4 bytes, replaces/extends today's `st3mot`):
  comm errors, checksum errors, kickstart counter, error code. Today's
  `st3mot` already carries `bodyTimeoutCount`/`checksumErrorCount`
  (2 bytes each) plus the experimental `kickStartCount` byte added
  2026-08-27/28 (see `analysis/grid_search_log.md`) — this planned
  4-byte layout needs reconciling with what's already there, including
  adding the new `errorCode` field, before implementation.

**Planned Kickstart Algorithm** (replaces the currently-built escalating-
repeat-count design, see the chronological log above for that one):
```
rpm == 0 and speed != 0:
  wait 400ms
  → rpm != 0? → closed loop
  → rpm == 0? → start kickstart

  6 attempts, 100ms apart:
    check rpm → rpm != 0? → immediately closed loop
    pulse 1: previous state (n-1)
    pulse 2: current state (n)
    pulse 3: next state (n+1)
    → next attempt

  after 6 attempts (400ms + 600ms = 1s total) → hard stop:
    → controlvariable = 0, integral = 0
    → errorCode = ERROR_MOTOR_STALL
    → wait for a Pi command (reset, presumably)
```
`wait 400ms` above is 4×100ms `SAMPLERATE` rpm-calc windows, matching
the threshold already decided 2026-08-26 (see `analysis/grid_search_log
.md`) — not necessarily final, may change (e.g. to 3×100ms) if further
testing suggests otherwise; check that log for the current reasoning
before assuming 400ms is settled.

**Pulse magnitude — decided, then revised down after a hardware
failure.** Real-hardware measurements 2026-08-28
(`characterize_hall_positions.py`, manual `pulse` testing) found actual
breakaway thresholds mostly in the 750-1100+ range — the old
`KICKSTART_SPEED=16` barely moved the rotor at all (an audible tick, no
measurable movement). `KICKSTART_SPEED=800` was tried next — this is
what led directly to the two-MOSFET burnout described in the Known
Hardware Issue section above (~63% duty into a stalled, zero-back-EMF
winding is a large overcurrent relative to the original 5A-target
derivation just above). **Now `const int16_t KICKSTART_SPEED =
GLOBALRATE/10;`** (~127, ~10% duty) — confirmed working since on real
hardware, no further hardware damage, but explicitly **not** treated as
settled: the user wants to revisit raising it again later, more
cautiously. See `analysis/grid_search_log.md`'s 2026-08-28
"KICKSTART_SPEED reconsidered" entry for the original breakaway-
threshold numbers this was checked against.

**Hall-sensor chattering (2026-08-28 finding) is a real, unresolved
risk this design only partially addresses.** Repeated `hal` reads with
the rotor stationary, right at a Tiefrast/Mittelrast sector boundary,
flickered between two adjacent electrical states — almost certainly
insufficient sensor hysteresis at the switching threshold (see
`analysis/grid_search_log.md`'s full writeup, including an observed
case of a commanded-CW pulse visibly driving the rotor CCW at such a
boundary). The 3-pulse (n-1/n/n+1) spread above is a genuine, sound
mitigation for the **commutation-targeting** side of this — since the
window covers both candidate states regardless of which one a single
ambiguous `hal` read returns, at least one of the three pulses should
apply correct-direction torque. **It does *not* address the
measurement side**: `hallCounter`/`rpm` are edge-counted via GPIO
interrupts, and chattering could inject spurious edges into that count
while the rotor is genuinely stationary — the failure mode already
suspected (not confirmed) as the root cause of the `rpm` "blip" bugs
found in `_detect_stiction()` (2026-08-26) and the original
`driveKickStart()` reset logic (2026-08-27). Whether this needs a
firmware-level debounce (e.g. require N consecutive identical Hall
readings before counting a transition) or is a hardware/mounting
limitation not fixable in software is not yet decided.

**A specific, reliably reproducible Mittelrast stall location found
(2026-09-09): between states 2 (`010`) and 3 (`110`), with `hal`
reading `010` (state 2, `data=['0x00','0x01','0x00']`) while stuck.**
Manually pushing the rotor into this exact Mittelrast reproduces the
stall on demand — confirmed multiple times, including through the
`capture_step_response.py` fixes above (`kickstart=3`/`sys_error=-65`
every time). Useful as a known, deliberate test position for kickstart/
pulse experiments going forward, instead of waiting for a stall to
happen at a random position. Not yet checked whether other
state-boundary Mittelrasten (e.g. 0↔1, 4↔5) are equally reproducible or
whether 2↔3 is special somehow — this is the only one confirmed so far.

**CW(+1)/CCW(+2) state-table asymmetry — empirically investigated
2026-09-08, inconclusive, then set aside rather than resolved.** The
user tried to directly verify the correct CCW physical neighbor state
by hand (read Hall state, manually turn the rotor into the next
detent, read again), but got **contradictory results between two
separate measurement attempts** (first: `current+1`; second, after the
user doubted the first: `current-1`, i.e. the exact reverse) — chased
partly by real Hall-chattering risk at the measurement points
themselves (see above), never resolved to a single trusted answer.
Rather than keep chasing it, the user fell back to the one thing that
*is* solidly validated: `driveStep()`'s own long-running real-hardware
behavior (`speed`, weeks of use, both directions) — and reasoned that
if `driveStep()` itself is trusted, its CCW `current+2` must be
accepted as correct too, asymmetry or not, rather than assumed to need
fixing. Practical consequence: `driveStepKickStartMinus()` was removed
from the manual `pulse` path entirely (see the Status section's `burst`
entry above) rather than have its CCW formula resolved — the open
question about *why* CW and CCW aren't simple mirror images of each
other is still genuinely unanswered, but no longer blocking anything,
since nothing in the current manual-pulse design depends on it anymore.
`driveKickStart()`'s automatic path still uses
`driveStepKickStartMinus()`/`Null()` internally, so this question is
still live there specifically, if it's ever revisited.

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

**Found and fixed a separate, genuine systematic bias in the same
measurement (2026-08-18): `TIM4`'s prescaler didn't produce an exact
1ms tick.** `htim4` clocks from the H7's 64MHz internal HSI (no PLL,
`SYSCLKSource=HSI`, `APB1CLKDivider=DIV2` → 32MHz PCLK1 → 64MHz TIM4
kernel clock via the standard APB timer-clock-doubling rule) with
`Prescaler=65534` (divide-by-65535) — giving a real tick period of
64MHz/65535 ≈ 1.024ms, not the 1ms the code implicitly assumes (both
here, via `SAMPLERATE=100` ticks meant to be "100ms", and in the
`delay(ms)` helper at `main.c:862`, which compares the raw counter
directly against a millisecond count). Since the RPM window actually
closes at ~101 ticks × 1.024ms ≈ 103.4ms of real time but `RPMFACTOR`
still divides by an assumed 0.1s, every `rpm` reading was inflated by
~3.4%. Confirmed against real data: a Saleae Hall-edge capture (true
ground truth, see `analysis/CLAUDE.md`'s Hall-Edge RPM Conversion
section) measured a steady-state mean of 963.6 vs. LIN `rpm`'s 998.2
for the same run — a 3.59% gap, matching the 3.42% predicted from the
tick-period math within measurement noise. **Fix:** `Prescaler=63999`
(divide-by-64000, 64MHz/64000 = exactly 1000Hz) — applied and flashed
2026-08-18. Not yet re-validated against a fresh Hall-edge capture with
the fix in place (the 2026-08-18 trigger-mode confirmation runs used
this fixed firmware, but weren't specifically designed to isolate this
~3% effect) — worth a dedicated before/after comparison if the
quantifiable size of the fix matters later, not just its direction.

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

**Two MOSFETs burned out (2026-09-08), replaced along with the
socket.** Happened while testing the kickstart redesign (see Planned
Redesign section above) at the old `KICKSTART_SPEED=800` (~63% duty,
~260A theoretical average current into a stalled/zero-back-EMF winding
— see the Planned Redesign section's `KICKSTART_SPEED` entry below for
the underlying 5A-target derivation this was already far above).
**Failure signature: the two "opposite/facing" MOSFETs of one
half-bridge** — the classic shoot-through pattern (high-side and
low-side of the same phase conducting simultaneously). Investigated
`driveState()`/`driveMOSFET()` closely for a same-phase-overlap or
missing-dead-time bug; found none introduced by the kickstart
refactoring — the far simpler, better-supported explanation is plain
overcurrent from the stalled-rotor pulse magnitude itself (no back-EMF
to limit current, only the ~65mΩ winding resistance), not a firmware
timing defect. User replaced both MOSFETs and the socket; before
retesting, `KICKSTART_SPEED` was reduced to `GLOBALRATE/10` (~127,
~10% duty, ~41A theoretical) and stayed there — see the Commutation &
Control section. Confirmed working since on the reduced value, no
further hardware damage. **Still open:** whether `KICKSTART_SPEED` can
safely go back up, and by how much — the user explicitly said this is
revisited later, not decided now.

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

**Bus-hang investigation (2026-08-11) — resolved and confirmed against
real hardware (2026-08-13).** Root cause: `HAL_UART_RxCpltCallback`'s
`else` branch (foreign-but-known pid, e.g. `st0cur` — the STM32 isn't
the addressee, it's only tracking the frame to keep its own header/body
sync) arms `HAL_UART_Receive_IT` for the full expected reply length with
no timeout. If the replying device (currentsensor) aborts mid-reply
(its own `aborted`/`break` echo-check logic, see
`currentsensor/CLAUDE.md`), the STM32 waited forever for bytes that
would never come — permanently deaf to all further LIN traffic, not
just to that one device, since the main loop never gets back to
re-arming the header receive.

- **Fix:** new globals near `rx_header`/`bodyrecvd` (`main.c:104-109`):
  `headerrecvd`/`bodyrecvd`/`bodysent` now `volatile` (were previously
  not — harmless only because the project builds at `-O0`, see below),
  plus `bodyWaitStartTick`, `bodyTimedOut`, `bodyTimeoutCount`,
  `LIN_BODY_TIMEOUT_MS` (50ms, generous above the ~4.7ms worst-case
  transmission time at 19200 baud). `bodyWaitStartTick = HAL_GetTick()`
  set right after each of the three `HAL_UART_Receive_IT(&huart4,
  rx_body, ...)` arm points in `HAL_UART_RxCpltCallback`
  (`main.c:779,787,795`). The timeout check lives in the main loop's
  `while (bodyrecvd == false)` wait (`main.c:303-309`): past
  `LIN_BODY_TIMEOUT_MS`, calls `HAL_UART_AbortReceive(&huart4)`
  (blocking variant — no DMA in use, effectively immediate; confirmed
  via `stm32h7xx_hal_uart.c:1807` that it resets `RxState` to `READY`
  cleanly, no side-effect callback), increments `bodyTimeoutCount`, and
  sets `bodyTimedOut` so the post-loop dispatch code
  (`main.c:381-384`) discards the partial/missing body and `continue`s
  straight back to re-arming `HAL_UART_Receive_IT(&huart4, rx_header,
  2)` instead of processing garbage.
- **`volatile` fix, same pass:** `headerrecvd`/`bodyrecvd`/`bodysent`
  are written in the ISR and read in the main loop but weren't marked
  `volatile` — silently relied on the project's current `-O0` build
  (confirmed via `STM32/firmware/Debug/Core/Src/subdir.mk`) never
  caching them across loop iterations. At any higher optimization level
  the compiler could legally hoist the `bodyrecvd` read out of
  `while (bodyrecvd == false)` entirely, turning it into a silent
  infinite loop. Fixed while touching this exact block.
- **`bodyTimeoutCount` exposed via `st3mot`** (`fillbody()`,
  `main.c:961-964`, 4 bytes little-endian, same convention as
  `st1mot`/`st2mot`) — this PID already existed in `addresses.json`
  reserved for exactly this purpose (motor's counterpart to
  currentsensor's `st1cur`); an earlier draft of this note incorrectly
  called it a "free block" needing reassignment, which was wrong — it
  was never free, just not dispatched yet. `raspi/watchdog/linbus.py`'s
  `get_motor_counters()` reads/decodes it.
- **Checksum handling added for master writes (2026-08-14).** The
  `sources[linindex] == master` ISR branch had a long-standing
  `// checksum sollte noch hier berechnet werden und gecheckt werden.`
  TODO — removed, since a checksum can't actually be verified there
  anyway (only the header has arrived at that point, not the body).
  Fix lives in the main loop instead, right after the `bodyTimedOut`
  guard, before the `cntl0mot`/`cntl1mot`/`cntl2mot`/`cntl3mot` dispatch
  blocks: `bool checksum_ok = (checksum(rx_body, linbodysize) ==
  rx_body[linbodysize]);`, ANDed into all five dispatch `if`s so a
  corrupted master write is silently dropped (fails closed) instead of
  acted on. `st3mot`'s `bodyTimeoutCount` (4 bytes) was split into two
  `uint16_t` fields the same day to add a matching
  `checksumErrorCount` without needing a new pid: `data[0:2]` =
  `bodyTimeoutCount` (unchanged, just narrowed from `uint32_t` — 16 bits
  is generous for a rare-event counter), `data[2:4]` =
  `checksumErrorCount`, incremented only when the failing checksum
  belonged to one of *our own* four `cntl*mot` pids (a separate
  `is_our_write` check), not any checksum mismatch merely snooped on the
  shared bus. See `raspi/CLAUDE.md`'s `selftest` entry for the raspi-side
  `provoke_checksum_error()` check built the same day.

  **Confirmed against real hardware (2026-08-14), same day as built.**
  `/build-stm32` clean (no warnings), flashed, then `selftest` run twice
  via `motorcontrol.py` (`runs/2026-08-14_checksum_test/`): motor idle
  the first time, running at commanded speed 500 the second time.
  `checksumErrorCount` went up by exactly 1 both times (`0→1`, then
  `1→2`), `bodyTimeoutCount` (from the same call's `bushang_test` part)
  climbed independently and `checksum` stayed flat during *that* part —
  confirms the two counters are genuinely independent, not
  cross-contaminating. Bonus indirect confirmation from the second run's
  `st2mot` poll trace: rpm climbed smoothly toward 500 (475→500) right
  through and after the corrupted "speed 0" write, with no dip — the
  rejected write visibly had zero effect on the real setpoint, not just
  on the counter. A **dedicated, deliberate** `rpm`-based before/after
  proof (send a corrupted *nonzero* target, confirm rpm does NOT chase
  it, then repeat with a correct checksum as a positive control) is
  still open — needs its own consent-gated command, discussed but not
  built yet (this session's confirmation was incidental, from a value
  chosen to be safe-by-default, not designed as the definitive test).

  **`is_our_write` scoping cross-confirmed (2026-08-15).** The
  currentsensor gained its own, analogous `cntl0cur` checksum-gate fix
  that day (see `currentsensor/CLAUDE.md`'s Status section) with its own
  `selftest` provocation — which incidentally also proved this device's
  `is_our_write` check correctly stays silent for a checksum failure
  addressed to a *different* device: `checksumErrorCount` stayed flat
  across both real-hardware runs even though the STM32 still tracks that
  `cntl0cur` frame going by on the shared bus (same ISR branch as its
  own `cntl*mot` writes). Confirms the scoping isn't just theoretically
  correct from reading the code, but actually discriminates by pid on
  real hardware.
- **Known accepted minor race, left as-is:** the timeout check
  (`main.c:303`) reads `headerrecvd`/`HAL_GetTick()` non-atomically. If
  `HAL_UART_RxCpltCallback` fires in that handful-of-CPU-cycles window
  (the real body completes right as the timeout is about to fire), a
  legitimate message could be discarded as if it were the failure case.
  Consequence is minor (master sees one spurious timeout on that read,
  can just retry) — would need `__disable_irq()`/`__enable_irq()` around
  the check to close fully, not done.
- **Confirmed against the real failure scenario (2026-08-13), not just
  built/flashed.** `raspi/control/motorcontrol.py`'s `selftest` command
  was extended (`linbus.provoke_bus_hang_timeout()`) to deliberately
  reproduce the original bug on demand: arms a matching sabotage flag on
  the currentsensor (`cntl0cur [0xfa,0x17]`, see
  `currentsensor/CLAUDE.md`) that forces its *own* echo-check to fail on
  the first byte of its next `st0cur`/`st1cur` reply, then triggers a
  real `st0cur` read. Run three times against real hardware, all
  consistent (`runs/2026-08-13_selftest_bushang*/`,
  `runs/2026-08-13_validate_capture/`):
  - Motor idle, twice back-to-back: `bodyTimeoutCount` `0→1`, then
    `1→2`; currentsensor's `st1cur` showed a fresh `CHK` entry both
    times; the *same* `selftest` call that provoked the hang could
    immediately read `st3mot`/`st1cur` back successfully (`ret=0`) —
    the STM32 was never stuck.
  - **Motor running at commanded speed 500 throughout:**
    `bodyTimeoutCount` `2→3`, `st0cur`'s reply cut off after exactly 1
    byte (`data=['0xf8']`, expected 4) as designed, and — the key
    result — `st2mot` read back **exactly 500 in the very next poll
    cycle** immediately after the ~2s provocation. `driveStep()`/
    `picontrol()` never glitched; the motor was fully controllable
    throughout and `speed 0` right after worked normally.
  - `validate_speed.py` and `capture_step_response.py` run clean
    afterward (`raspi/analyze_logs.py`: no anomalies) — no regression
    from the fix in normal operation.
  - The originally-planned *separate* currentsensor-side error counter
    (to correlate against `bodyTimeoutCount`) turned out unnecessary —
    the existing `errorstorage`/`st1cur` already gave that signal, and
    the correlation (STM32 counter and currentsensor `CHK` entry moving
    together, every time) was directly observed via this test.

**Dead-code cleanup (2026-08-15) — `main.c` only, confirmed against real
hardware same day.** `main.c` had accumulated a substantial amount of
genuinely unreachable code, found by grepping every candidate symbol
across the whole firmware tree (`Core/Src/*.c`, `Core/Inc/*.h`), not
just reading main.c in isolation:
- Both `#ifdef BLUBBER` blocks — `BLUBBER` is never `#define`d anywhere
  (checked source and `.mk` build flags), so both were provably
  unreachable.
- An entire second, never-invoked commutation implementation:
  `setup()`, `runMotor()`, `readHall()`, `findIndex()`, `nextStep()`,
  `step()`, `doStep()` — an apparent early Arduino-style bring-up
  iteration, superseded by the actual live path
  (`driveStep()`/`driveState()`/`getState()`, called from `main()`'s
  loop via `picontrol()`) but never deleted. Confirmed dead by tracing
  the call chain: `main()` never calls `setup()` or `runMotor()`, and
  every other function in the chain is only ever called from within it.
  `step()`'s `switch` even had a real bug (missing `break` on `case 0`,
  falls through into `case 1`) — harmless only because the whole chain
  was unreachable, exactly the kind of landmine dead code leaves behind.
  Plus the globals only that chain used: `POT_PIN`, `STEP_DELAY`,
  `lastHallIndex`, `side`, `states[]`, `pwmRate`, `pulseWidth`,
  `statusK`, `lastButtonStateStart`, `lastButtonStateStop`,
  `dirmeasured`, and the vestigial `oldstep`/`newstep`/`speedcount`
  comments tied to the first `BLUBBER` block.
- **Explicitly kept, checked first:** `allOff()`/`driveMOSFET()` (also
  called from the live `driveState()`, so not dead) and
  `directionMatrix`/`previousState`/`hallCounter` (declared `volatile`
  in `main.c`, `extern`'d via `main.h`, and actually incremented/read in
  `stm32h7xx_it.c`'s real Hall EXTI interrupt handler — only their
  in-`main.c` reference was inside the dead `BLUBBER` block, the
  declarations themselves are live). Confirmed via grep across the
  other source files before deleting anything, without editing them —
  user's instruction this pass was `main.c` only.
- 245 lines removed, nothing else changed. `/build-stm32`: clean, no
  warnings, and — notably — **binary size identical bit-for-bit**
  (`text=48264/data=16/bss=2032`, same as the pre-cleanup build) to the
  build just before this cleanup. Expected: the linker already runs
  with `--gc-sections`, so this code was already being stripped from
  the flashed `.elf` regardless of whether it existed in source — this
  cleanup removed source clutter, not flash bytes.
- **Flashed and confirmed on real hardware (2026-08-15).** `speed 0` →
  `speed 500` → `speed 0` worked normally both before and after running
  `selftest` (`runs/2026-08-15_post_cleanup/`) — direct confirmation
  that the live commutation path (`driveStep`/`driveState`/`getState`,
  deliberately left untouched) still works correctly. `selftest` itself
  also came back clean: errorstorage roundtrip, the currentsensor
  checksum-gate test, the bus-hang test, and the STM32 checksum test all
  produced the same correct, mutually-isolated counter behavior as every
  previous run this week — no regression from the cleanup.


**UART receive-error found and fixed (2026-09-08) — a second, distinct
permanent-hang bug, different from the 2026-08-11 one above.** That
earlier bug was a foreign-PID body that never fully arrived; this one
is a genuine hardware UART overrun on the STM32's own reception.

Root cause: `cntl1mot` (`pulse`)'s handler was extended (2026-09-07/08,
see the Planned Redesign section above) to chain several `driveStep()`
calls per LIN message (a reverse-then-forward "rock back" pulse
sequence) — roughly ~5ms of blocking per `pulse` call, instead of the
~1275µs any other simple dispatch handler takes. `HAL_UART_Receive_IT()`
for the next header is only re-armed once per `for(;;)` loop iteration,
after the whole dispatch finishes — a pre-existing, previously
negligible gap that this redesign widened ~4x. If a byte arrives during
that gap — in practice, the Raspi watchdog's own independent background
`poll_rpm()`/`poll_current()` thread (runs every ~1s, has no knowledge
of what the STM32 is doing at any given instant) — the UART sets an
Overrun (ORE) error, and with no code clearing it, **the peripheral
stops receiving anything at all, permanently, until physically reset.**
Confirmed via `watchdog.log`: a `[poll] -> read st2mot` landing 19ms
after a `[client] -> write cntl1mot` produced a full 2s pyserial
timeout, and every subsequent poll for the rest of that session (>15s)
timed out identically — not a one-off missed poll, a permanent hang.

**Fix: `HAL_UART_ErrorCallback(UART_HandleTypeDef *huart)` override**,
added next to the existing `HAL_UART_RxCpltCallback` in `main.c`
(previously relied on the HAL's default no-op weak implementation, so
nothing ever ran on this path). Clears `ORE`/`FE`/`NE` flags, resets
`headerrecvd`/`bodyrecvd`/`bodysent` (mirrors what
`HAL_UART_RxCpltCallback` itself maintains), sets `sysError =
LIN_RCV_ERR` (`errors.h` — the value was already reserved, just unused
until now) so the event is visible via the new `status` command below,
then `HAL_UART_AbortReceive(&huart4)` followed by
`HAL_UART_Receive_IT(&huart4, rx_header, 2)` to force reception back
on. **The explicit `AbortReceive` call turned out to be load-bearing**
— a first version without it (flag-clear + re-arm only) still left the
STM32 permanently deaf after a collision; only after adding it did the
STM32 visibly recover. Confirmed on real hardware the same day: a
~1.3s-delayed `pulse` reply (the collision happening), immediately
followed by `status` reading back `sys_error=-8` (`LIN_RCV_ERR`), then
every subsequent command for the rest of that session responding
normally again — no further `ret=-5` at all.

**Two new commands, built the same day as part of this investigation:**
- **`status`** (`watchdog.py`/`motorcontrol.py`, standalone): a plain
  on-demand read of `st3mot` via `linbus.get_motor_status()` — the same
  data `selftest`'s reset_test part already reads before/after a
  reset, now directly callable for diagnostics like this one without
  running the whole `selftest` sequence.
- **`burst <value1> <pause1_ms> <value2> <pause2_ms>`**: the Pi-side
  replacement for `cntl1mot`'s STM32-internal multi-`driveStep()` pulse
  sequence that caused this bug in the first place. Sends two separate,
  single-pulse `cntl1mot` writes (`linbus.set_pulse()`) with Python-side
  `time.sleep()` pauses in between and after, instead of chaining
  several `driveStep()` calls inside one LIN dispatch. This (a) shrinks
  the STM32-side blocking window per message back to ~1275µs (matching
  every other simple dispatch handler — the same order of magnitude
  that ran fine for weeks before this redesign), and (b) makes the
  pause between the reverse and forward pulse tunable per-call from the
  Pi, no firmware rebuild needed. Runs entirely under `watchdog.py`'s
  own `self.lock`, so the background poll thread can't interleave a
  request during a `burst` call either — the collision class this
  section describes can now only happen from `poll_rpm()`/
  `poll_current()` colliding with a single, ordinary ~1275µs-blocking
  dispatch handler (the same low background risk level that predates
  this whole investigation and was never observed as a problem before),
  not from `burst`'s own two writes racing each other.
- **`main.c`'s `cntl1mot` handler reverted to a single, plain
  `driveStep(speedlocal)` call** (matching `speed`'s handler shape),
  replacing both the old throwaway UART-bug-reproduction test code (a
  bare ~55ms `delay_us()` chain) and the multi-`driveStep()` "rock
  back" sequencing that caused this bug in the first place — that
  sequencing now lives in the Pi's `burst` command instead. **Confirmed
  working well on real hardware the same day** (`burst` reliably
  overcoming Mittelrast sticking points, no further UART hangs
  observed).
- **Correction (2026-09-09): `driveKickStart()` was never actually
  vulnerable to the UART collision above, unlike originally documented
  here.** `driveKickStart()` is called from *inside* the main loop's
  `while (bodyrecvd == false)` loop, where `HAL_UART_Receive_IT()` for
  the next header is already armed (from `for(;;)`'s top, before the
  while loop) — an incoming header byte is caught by interrupt
  regardless of what the foreground code is doing in a `delay_us()`
  busy-wait, since that only polls a timer register and never disables
  interrupts. The actual vulnerable gap was specifically the *dispatch*
  section (`cntl0mot`-`cntl3mot` checks, after the while loop exits) —
  header reception isn't re-armed there until the next `for(;;)`
  iteration, which is what made the old multi-`driveStep()` `cntl1mot`
  blocking dangerous. `driveKickStart()`'s own blocking was never in
  that gap.
- **`driveKickStart()` also simplified (2026-09-09):** dropped the
  escalating-repeat-count `while` loop and the
  `driveStepKickStartMinus()`/`Null()`/`getState()` calls entirely — it
  now fires a single `driveStep(speed >= 0 ? KICKSTART_SPEED :
  -KICKSTART_SPEED)` per triggering 100ms window, same simple pattern
  as `cntl1mot`. This also removes the escalation-×-future-
  `KICKSTART_SPEED`-increase current-stress concern raised in an
  earlier review — total pulses per stall event is now capped at
  `KICKSTART_STUCK_UPPER_WINDOWS - KICKSTART_STUCK_LOWER_WINDOWS + 1`
  (5), not the old up-to-30.

**Deferred: a deterministic `selftest` provocation for this specific
UART receive-error path (2026-09-08).** Unlike the checksum/bus-hang
`selftest` provocations above (content-based — a specific bad byte
pattern, deterministically reproducible on demand), this bug is a
**timing race** between two independently-clocked things (STM32-side
blocking duration vs. the Pi's ~1s poll interval) — no LIN payload
reliably triggers it by itself. A reliable test would need either
fragile Python-side timing (OS scheduling jitter) or a dedicated,
permanent firmware test hook (an artificial "don't listen for N ms"
command, similar in spirit to today's throwaway test code) purely to
exercise recovery. Deferred rather than built: `burst` above is
expected to shrink the STM32-side blocking window back to normal-
dispatch-handler size, reducing how often this race can even occur in
real use — revisit whether a dedicated test hook is still worth its
permanent complexity once real-world `burst` usage shows how residual
the risk actually is.

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
- Implement Hall-based stall detection (see Stall Detection section
  above) — deprioritized, was sequenced after the standalone-build-
  environment goal; both build and flash are now headless, so this can
  be reconsidered/picked up next. When it happens: timeout/threshold not
  yet chosen, needs tuning against real startup behavior (torque needed
  to overcome static friction before the first Hall transition must not
  trigger a false stall trip).
- **From the 2026-09-07 high-priority list — status update:**
  - `reset` command: **done** (built and confirmed 2026-09-07, see the
    Status section above).
  - `status` reply restructure (6-byte `st3mot`, `sysError` field):
    **done** (built 2026-09-07, extended with the UART-error fix's
    `LIN_RCV_ERR` value 2026-09-08, see the Status section above).
  - The `pulse` command's multi-pulse sequence: **built, then
    redesigned again.** The original 3-pulse (n-1/n/n+1) idea became a
    `driveStepKickStartMinus/Null/Plus` implementation, then (after the
    2026-09-08 UART-hang investigation, see Status section above) that
    sequencing logic moved to the Pi's new `burst` command instead —
    **done**, `cntl1mot` is back to a single, plain
    `driveStep(speedlocal)` call, confirmed working well on real
    hardware (2026-09-08). `driveKickStart()`'s own internal
    sequencing was also simplified the next day (2026-09-09): dropped
    the escalating-repeat-count loop and
    `driveStepKickStartMinus/Null/Plus` entirely, now a single
    `driveStep()` per triggering window — see the Status section's
    2026-09-09 entries (including a correction: this path was never
    actually vulnerable to the UART collision, unlike first assumed).
  - Systematically pulse-test all 24 mechanical positions (Tiefrast +
    Mittelrast): still not started — extends, not replaces, the manual/
    semi-automatic characterization already done 2026-08-28
    (`characterize_hall_positions.py`, see `analysis/grid_search_log.md`).
    Blocked on the `pulse`/`burst` design actually settling first.
- **Deferred (2026-09-08):** a deterministic `selftest` provocation for
  the UART receive-error path — see the Status section above for why
  (timing race, not content-based) and what would revisit this.

Fill these in here once fixed, not in the root `CLAUDE.md`.
