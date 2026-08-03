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

- Built and flashed via STM32CubeIDE / `STM32_Programmer_CLI`, both
  installed on the Windows host (the "STM32 host" machine in the root
  `CLAUDE.md` — this machine, not the STM32 controller being flashed).
- Build/flash automation is meant to live here in `STM32/` — not yet
  implemented, directory is currently empty.
- **Goal (needs evaluation):** a standalone build/flash environment in
  `STM32/` that doesn't require STM32CubeIDE itself — e.g. driving the
  underlying toolchain (GCC + `STM32_Programmer_CLI`, or CMake) directly.
  Not yet evaluated whether that's practical given the existing CubeIDE
  project setup (see `STM32/notes.md`'s project file tree).

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

Not yet imported into this repo — directory currently only has
`.gitkeep`. The actual firmware is an existing STM32CubeIDE project on
this machine (project files named `demoboard`/`BringUpBoard`; see
`STM32/notes.md` for its full file tree) — not yet located/linked into
this repo.


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

- Exact trigger-pin GPIO assignment.
- Build/flash automation script.
- Evaluate whether a standalone (non-STM32CubeIDE) build/flash setup is
  feasible for this project — see the Build & Flash goal above.
- Implement Hall-based stall detection (see Stall Detection section
  above) — deprioritized, sequenced after the standalone-build-
  environment goal, not before. When it happens: timeout/threshold not
  yet chosen, needs tuning against real startup behavior (torque needed
  to overcome static friction before the first Hall transition must not
  trigger a false stall trip).

Fill these in here once fixed, not in the root `CLAUDE.md`.
