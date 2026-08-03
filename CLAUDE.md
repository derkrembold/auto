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
  plus a trigger channel. Handles speed measurement entirely — no more
  reading measurement data back over LIN.

## Data Flow / Control Channels

- **Control (LIN, already implemented):** Raspi → STM32 controller.
  Command: set speed (0 = stop).
- **Measurement (Saleae, non-invasive):** The 3 Hall sensor signals are
  needed for commutation anyway — the Saleae just taps them, without
  requiring any firmware changes. Instantaneous speed is computed from
  them in software (time between edge transitions).
- **Trigger pin:** An additional free GPIO pin on the STM32 controller is
  set high when the control algorithm starts (directly in the code path
  that also triggers motor start) and set low again on stop. This pin
  runs as the 4th channel in the Saleae capture and serves as a hardware
  trigger for capture start — no software synchronization between
  systems needed.

## Repo Structure

```
Auto/
├── STM32/          Firmware + build/flash automation (STM32 CLI)
├── raspi/
│   ├── control/    LIN master code (speed command) — already implemented
│   └── watchdog/   Independent safety barrier, runs separately from the rest
├── currentsensor/  Planned LIN slave — firmware/ + reference notes
├── lightsensor/    Planned LIN slave — firmware/
├── saleae/
│   ├── capture_config/   Channel mapping, trigger setup, sample rate
│   └── exports/          Raw capture exports per test run
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

Currently 1 motor slave. Planned expansion: 2 motor slaves, 1 current
sensor, 1 light sensor — all as LIN slaves on the same bus, addressed
via the same `linaddresses.py`/`addresses.h` scheme (each slave gets a
control PID and/or status PID, as applicable). Keep the PID table
structure generic rather than hardcoded to a single slave when extending
it, but don't build support for slaves that don't exist yet.


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
- Saleae-specific open points (pin mapping, sample rate) — see
  `saleae/CLAUDE.md`.
- Analysis-specific open points (cost function/metric weighting) — see
  `analysis/CLAUDE.md`.
- Deployment mechanism repo → Raspi (script still to be built).
- Verify that the `speed` value sent via LIN (`raspi/control/motorcontrol.py`)
  actually corresponds to RPM — currently assumed, not confirmed against
  measured speed. Check once the Saleae Hall-edge speed measurement is
  working. Note: battery state of charge (see Battery section above)
  changes supply voltage, which itself changes motor speed — control
  for that when verifying, don't attribute all speed variation to
  `speed` alone.
