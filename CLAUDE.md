# Auto — Automated BLDC Motor Test and Optimization Tool

This file is organized so a future split into separate `concept.md` /
`architecture.md` files (if it ever gets overloaded) is just "cut this
section out" — no rewriting needed.

# Concept

The "why" — rarely changes.

## Goal

Autonomous optimization loop for a BLDC motor control algorithm on an
STM32 controller. A parameter set is built, flashed, the motor runs for a
test interval, the speed is measured, control metrics are computed from
that, and the next parameter set is derived from them.

## Documentation Language

Documentation in this repo is in English. Some descriptions (e.g. parts
of `STM32/CLAUDE.md` and `STM32/notes.md`, copied from pre-existing
German working notes) are still in German — translate them to English
as you touch them, rather than leaving them as a standing exception.

# Architecture

The "how" — evolves as the system gets built out.

## Machines/Devices Involved

- **STM32 host (Windows, this machine)**: Claude Code runs here.
  STM32CubeIDE/STM32_Programmer_CLI is installed here, and the Saleae
  Logic Pro 16 is also connected here.
- **STM32 controller**: Runs the control algorithm, drives the BLDC motor.
- **Raspberry Pi**: A pure execution node with no AI of its own. Sends
  LIN bus commands (Speed, 0 = stop) to the motor controller. Is
  remote-controlled by Claude Code over SSH (upload scripts, run them,
  read back results).
- **Saleae Logic Pro 16**: Records the motor's 3 Hall sensor channels
  plus a trigger channel. Precision speed measurement for PI-parameter
  optimization, and for validating the LIN `rpm` reading against ground
  truth — see the Measurement bullet below. Not part of the operational/
  production system — `raspi/watchdog/` reads `rpm` over LIN for that,
  see its CLAUDE.md.

## Data Flow / Control Channels

- **Control (LIN, already implemented):** Raspi → STM32 controller.
  Command: set speed (0 = stop). All communication with the STM32 is
  over LIN, always — the Saleae is a measurement tool, not a control or
  operational data channel.
- **Measurement (Saleae, non-invasive, for optimization + validation
  only):** The 3 Hall sensor signals are needed for commutation anyway —
  the Saleae just taps them, without requiring any firmware changes.
  Instantaneous speed is computed from them in software (time between
  edge transitions). Two purposes: (1) precise speed feedback for tuning
  the PI parameters, (2) validating the LIN `rpm` reading against this
  ground truth — see the open "does `speed` really mean RPM?" question
  below. This is a dev-time/lab tool, not part of the deployed/
  operational system — the watchdog's own `rpm` polling over LIN (see
  `raspi/watchdog/CLAUDE.md`) is the operational speed-monitoring
  channel, and is unaffected by this Saleae scoping.
- **Trigger pin:** An additional free GPIO pin on the STM32 controller is
  set high when the control algorithm starts (directly in the code path
  that also triggers motor start) and set low again on stop. This pin
  runs as the 4th channel in the Saleae capture and serves as a hardware
  trigger for capture start — no software synchronization between
  systems needed.

## Repo Structure

```
Auto/
├── addresses.json          Single source of truth for LIN PIDs (see LIN Protocol section)
├── generate_addresses.py   Generates addresses.md + writes directly to every consuming file
├── addresses.md            Generated "at a glance" occupied/free PID map
├── run_experiment.py       Standalone P/I grid/gradient-search point runner (see raspi/CLAUDE.md)
├── STM32/          Firmware + build/flash automation (STM32 CLI)
├── raspi/
│   ├── control/    LIN master code (speed command) — already implemented
│   └── watchdog/   Independent safety barrier, runs separately from the rest
├── currentsensor/  Planned LIN slave — firmware/ + reference notes
├── lightsensor/    Planned LIN slave — firmware/
├── saleae/
│   ├── capture_config/   Channel mapping, trigger setup, sample rate
│   └── exports/          Raw capture exports per test run
├── saleae_mcp/     MCP server wrapping the Saleae Automation API (see saleae/CLAUDE.md)
├── analysis/       Speed calculation from Hall edges, control metrics
└── runs/           Per iteration: parameter set, raw data, metrics
```

`raspi/*` is developed/versioned here in the repo, but deployed to the
Raspi via SSH/SCP — the Raspi itself is only a deployment target, not a
git checkout.

Pi-specific details (SSH access, deploy mechanics, LIN protocol quirks,
motor-execution consent rule) live in `raspi/CLAUDE.md`, not here — this
file stays scoped to whole-system concept/architecture.

Saleae-specific details (channel mapping, trigger/sample-rate config) live
in `saleae/CLAUDE.md`, not here.

Analysis-specific details (speed calculation, cost function/metrics) live
in `analysis/CLAUDE.md`, not here.

STM32-specific details (firmware, build/flash, motor specs, LIN slave
side) live in `STM32/CLAUDE.md`, not here.

Current-sensor-specific details (planned LIN slave, reference material
from a related university course project) live in
`currentsensor/CLAUDE.md`, not here.

Light-sensor-specific details (planned LIN slave, firmware starting
point from the same course project) live in `lightsensor/CLAUDE.md`,
not here.

## Experiment Runner (`run_experiment.py`)

**Built 2026-08-19.** Standalone, no-Claude-needed script (repo root)
that runs one full grid/gradient-search point end to end: physical
pre-flight checklist → P/I delta input (as CLI args or interactive
prompts) → motor-start consent → sets `KP`/`KI` via `raspi/control/
capture_step_response.py --p-delta/--i-delta` (which itself sends the
`pi` command first and aborts before touching the motor if the
watchdog rejects the range) → arms the Saleae in `trigger` mode, runs
the motor, retries up to 3x if the trigger false-fires on EMI noise →
`raspi/analyze_logs.py` sanity check → Hall-vs-LIN-plus-current overlay
plot. This is the intended single-point mechanism a future grid/
gradient search loop (see the Goal above) would call repeatedly with
different `--p-delta`/`--i-delta` values, not just a one-off
convenience script.

Deliberately does **not** re-check the P/I range itself — the
watchdog's own `validate()` (`raspi/watchdog/watchdog.py`'s
`PI_DELTA_MIN`/`MAX`) is the single source of truth for that, avoiding
two independent range definitions drifting apart over time. See
`raspi/CLAUDE.md`'s `capture_step_response.py`/`pi` entries,
`saleae/CLAUDE.md`'s Trigger pin section (the false-trigger retry logic
this reuses), and `analysis/CLAUDE.md` (`hall_rpm.py`,
`has_sustained_high()`) for the pieces this wires together — this
section only covers the orchestration, not each piece's own design
history.

**Confirmed end-to-end on real hardware the same day, including a real
bug found and fixed live.** First run: the `watchdog.log`/
`capture_step_response.log` fetch step didn't check `scp`'s return
code, so one transient fetch failure was silently swallowed and
`analyze_logs.py` crashed downstream with a confusing
`FileNotFoundError` instead of a clear message — the actual experiment
(checklist through the plot) had completed successfully regardless.
Fixed: each log fetch retries up to 3x (matching the `/analyze-logs`
skill's own documented `motorpi.local` mDNS-flakiness note), only
successfully-fetched files are passed to `analyze_logs.py`, and a
still-failing fetch after retries prints a clear warning instead of
crashing anything downstream. Second run (`pi 0.01 0.01`, a real
nonzero delta) confirmed fully clean: real trigger caught on the first
attempt, both logs fetched, `analyze_logs.py` found only the two
expected/benign WARNINGs (disconnect + one observe-only stall
signature during coast-down), Hall/LIN rpm agreed closely throughout.

**Second real bug, same day: the script didn't exit on its own —
needed Ctrl-C even after a fully successful run.** Root cause and fix
(`saleae_mcp/server.py`'s new `close_manager()`, called in a `finally`
block around `main()`) are documented in `saleae/CLAUDE.md`'s MCP
Server section, not duplicated here — in short, the Saleae
`automation.Manager` connection was never explicitly closed, which
kept the process alive after `main()` returned. Confirmed fixed live:
a bare connect+`close_manager()` cycle now exits promptly on its own.

## LIN Protocol
### Header Operation
The header operation is like this:
* write a syncbyte
* read if syncbyte has been sent, compare with the write byte
* write a address with added parity
* read if byte has been sent, compare with the write byte
* The address has an associated number. The number you find in linaddresses.py. The address also tells you, if this is a pure write (master to slave), and actually a read (slave to master).

The header operation is a requirement for both reading and writing
messages. After the header, both sides look up the address: raspi in
`linaddresses.py`, the motor (STM32) in its equivalent `addresses.h`.
Both tables must agree on the same address → direction mapping — the
direction (write or read) is not chosen per-message, it's committed to by
the address itself, ahead of time, on both ends.

### Master to Slave
this is the write operation. number of bytes are sent to slave. After writing a byte, you always need to read, and compare!
A checksum is sent.

### Slave to Master
this is the read operation. number of bytes are read from slave.
Finally a checksum is received from the slave. No write/read-compare here
— the slave is the transmitter during this phase, there is nothing of
ours to echo-compare against. The write/read-compare requirement applies
to the header only.

### Slave Topology

Currently 1 motor slave, live on the bus. `addresses.json` (see below)
already reserves room for more: up to 4 motors, 2 current sensors, 2
light sensors — reserved capacity in the addressing scheme, not a claim
that this hardware exists yet. Keep the PID table structure generic
rather than hardcoded to a single slave, but don't build device
firmware/support for units that don't exist yet.

### Address Table Single Source of Truth (In Progress)

With 3+ separately hand-maintained address tables
(`raspi/control/linaddresses.py`, `STM32/`'s `addresses.h`,
`currentsensor/firmware/addresses.h`, soon `lightsensor/` too, plus
future motor slaves), manual sync is a proven bug source — the DCPS
course project's own notes (`currentsensor/notes.md`, Problems 8 & 10)
document exactly this failure mode happening once already, and it
resurfaced live in this project too: `currentsensor/firmware/addresses.h`
was still using the motor's own PIDs, with different message byte
counts for the same PID names — a real collision waiting to happen once
current-sensor hardware actually joins the bus, not just a theoretical
risk.

**Design (settled 2026-08-05):** `addresses.json` (repo root) is now the
single canonical source. `generate_addresses.py` (repo root) generates
from it:
- `addresses.md` (repo root) — human "at a glance" occupied/free PID
  map, shown block-wise (see addressing model below).
- `linaddresses.py` (the master/raspi's view) — every message across
  every device class; `sources`/`destinations` are strings (including
  `"master"`) naming a device *class*, not a fixed wire address.
- `addresses.h` — **one single file, byte-for-byte identical for every
  embedded target** (STM32, currentsensor, lightsensor, future motor
  slaves) — no per-target filtering. Message names are already globally
  unique across classes, unused `const uint8_t`s cost effectively
  nothing, and firmware already decides what to act on via PID
  comparison regardless of what else happens to be declared in the
  header. `sources`/`destinations` there use small distinct `uint8_t`
  sentinels (`master`, `motor`, `current`, `light`) mirroring the Python
  class-name strings, since C can't put strings in a `uint8_t[]` —
  each non-`master` sentinel is that class's own lowest block-base pid
  (e.g. `current` = `cntl0cur`'s pid, `0x20`), used purely as a tag in
  `sources[]`/`destinations[]` and never compared against `pids[]`.

**Addressing model — multiple identical physical units, one firmware
image each:** up to 4 motors (and multiple current/light sensors)
planned, but firmware must stay byte-identical across every unit of one
device type — so no single unit's PID can be baked in at compile time.
Instead:
- The lowest 2 ID bits of every message's PID are reserved for an
  **instance number** (0-3; only 1 bit is actually used today for
  current/light, which have 2 instances each). Message *type* occupies
  the remaining upper ID bits — every message's base PID in
  `addresses.json` is a multiple of 4 (one 4-PID "block" per message
  type). A separate `instances` list (`{"class": "motor", "num": 0,
  "id": "0x00"}`, ...) gives each physical instance's 2-bit offset.
- The actual on-wire PID for message X addressed to instance N is
  `base_pid(X) | id(N)` — computed at **runtime**, not compile time.
- Each physical board determines its own instance number at boot from
  **hardware strap pins**, not from a firmware source difference — on
  the STM32 motor controller, `PB14`/`PB15` read via internal pull-ups,
  jumper-to-GND to select (see `STM32/CLAUDE.md`'s Buttons/Switches
  section). This is what actually makes byte-identical firmware across
  multiple physical units possible.
- `addresses.md`'s block table is the "at a glance" check for this:
  which 4-PID blocks are occupied by which message type, how many
  instance slots within a block are still free, and which blocks are
  entirely free for future message types.

**Writes directly to the real consuming files** — `raspi/control/
linaddresses.py`, `STM32/firmware/Core/Inc/addresses.h`, and
`currentsensor/firmware/addresses.h` — no `generated/` staging step.
An earlier, temporary review-before-adopt phase wrote drafts to
`generated/` (gitignored) instead while the addressing scheme itself
was still being hand-reviewed; that phase ended 2026-08-06, confirmed
by `generate_addresses.py`'s own docstring. Edit `addresses.json`, then
re-run the generator — never hand-edit the generated files directly.

**Not yet done — see Open Points below**: wiring the runtime
jumper-read into actual firmware dispatch logic.


## Battery

**Open decision: 8S vs 9S (24V vs ~28.8V nominal) — not yet decided, see
Open Points below.** 9 cells were ordered (1 originally as a spare), and
9S has been evaluated as viable (BMS supports 8S–20S; motor's 36V max
comfortably covers 9S's ~32.9V full-charge; the Victron buck converter's
36V input rating covers it too) — but no final call has been made yet.
Text below describes 8S/24V as that's the current bench setup's
voltage (per `STM32/notes.md` "Betriebsbedingungen") — treat any "24V"
below as provisional, not a settled spec, until this is decided.

8 Batteries (9 ordered, 1 as spare unless 9S is chosen):
* REPT CB56 - 100Ah - LiFePO4 3.2V - Grade A

100Ah (~2.56kWh) is intentionally sized for future mobile use, not just
the current bench-test phase — don't read it as oversized/a mismatch for
the test rig.

1 BMS:
* JK Smart Active Balance BMS BD6A20S8PR - (8S - 20S) - 80A - LiFePO4 / Li-ion

Note: 8S1P LiFePO4 is nominally ~25.6V (8 × 3.2V), commonly labeled
"24V" as a class, but actual pack voltage swings roughly 29V (full) to
20V (near empty) across a discharge cycle — it is not a fixed 24V. Since
motor no-load speed scales with voltage (~105 RPM/V, see
`STM32/CLAUDE.md`), this voltage swing is a plausible confound for the
open "does `speed` really mean RPM?" question below, separate from the
LIN `speed` parameter itself.

## Buck Converter
The Buck converter convers 24V from the battery to 12v. The Raspi itself has a shield, which converts 12V to 5V.
This 7A/60W converter only powers the Raspi's logic — the motor draws
directly off the 24V battery, not through this converter (a 1000W motor
obviously can't run through a 60W supply).

Buck Converter
* Victron Orion-Tr 24/12-5


# Safety

Cross-cutting — applies regardless of concept/architecture changes.

- **The watchdog on the Raspi (`raspi/watchdog/`) is independent of the
  optimization loop and of Claude Code.** It runs as its own process and
  stops the motor on its own if, e.g., no heartbeat/command arrives for
  too long. Limits (max speed, etc.) belong in the code, not in prompts
  or Claude-side discipline.
- **Current sensing is currently physically disabled** on the STM32
  board — the current-sense shunt blew and was bridged with a copper
  wire (see `STM32/CLAUDE.md`). Any safety limit that assumes current
  measurement is available does not work right now; only time/speed-based
  limits are actually enforceable.
- A manual emergency-stop path must be triggerable at any time,
  independent of the loop.

# Open Points / Still To Be Clarified

Living tracker — remove items once resolved.

- **8S vs 9S battery decision** (24V vs ~28.8V nominal) — not yet
  decided. See Battery section above.
- **`addresses.json`/`generate_addresses.py`** — design settled and
  built (2026-08-05), writes directly to every consuming file since
  2026-08-06 (no more `generated/` staging), see LIN Protocol "Address
  Table Single Source of Truth" section above. Remaining concrete step:
  - Wire the actual runtime jumper-read (`PB14`/`PB15` → instance
    number → `base_pid | id`) into STM32 `main.c`'s LIN dispatch logic
    — the jumper *reading* itself is hardware-confirmed working
    (2026-08-05), but the dispatch logic still uses the old flat,
    single-motor constants.
  - Same runtime treatment needed in `currentsensor`/`lightsensor`
    firmware once they're built for multiple physical units.
- Saleae-specific open points (pin mapping, sample rate) — see
  `saleae/CLAUDE.md`.
- Analysis-specific open points (cost function/metric weighting) — see
  `analysis/CLAUDE.md`.
- **`speed` ≈ `rpm`, confirmed live (2026-08-04) — no longer just
  assumed.** `raspi/control/validate_speed.py` (0 → 400 → 800 → 1200 →
  800 → 400 → 0 → -400 → -800 → -1200 → -800 → -400 → 0, `rpm` checked
  after every step) ran clean end to end: `rpm` tracked `speed` to
  within roughly ±6% at every step (e.g. 400→450, 800→825, 1200→1175,
  -1200→-1200, back to 0→0), both directions, ramp up and back down.
  Good enough to treat `speed`≈`rpm` as validated for now.
  **Independent ground truth done (2026-08-17/18):** a real Saleae
  Hall-edge capture during a live `capture_step_response.py` run,
  converted to rpm via `analysis/hall_rpm.py`, tracks LIN `rpm` closely
  across ramp-up/steady-state/coast-down — see `analysis/CLAUDE.md`'s
  Hall-Edge RPM Conversion section. This *is* the independent
  measurement the validate_speed.py run above couldn't provide on its
  own. Along the way, found and explained a genuine small systematic
  bias in LIN `rpm` itself (~3.4%, from `TIM4`'s prescaler giving a
  ~1.024ms tick instead of exactly 1ms — see `STM32/CLAUDE.md`'s RPM
  Measurement Resolution section) — since fixed in firmware
  (`Prescaler=63999`). **Still not done:** explicitly controlling for
  battery-voltage drift (see Battery section above) across a longer
  run/discharge cycle.
