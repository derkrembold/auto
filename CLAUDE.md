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


# Safety

Cross-cutting — applies regardless of concept/architecture changes.

- **The watchdog on the Raspi (`raspi/watchdog/`) is independent of the
  optimization loop and of Claude Code.** It runs as its own process and
  stops the motor on its own if, e.g., no heartbeat/command arrives for
  too long. Limits (max speed, etc.) belong in the code, not in prompts
  or Claude-side discipline.
- A manual emergency-stop path must be triggerable at any time,
  independent of the loop.

# Open Points / Still To Be Clarified

Living tracker — remove items once resolved.

- Saleae-specific open points (pin mapping, sample rate) — see
  `saleae/CLAUDE.md`.
- Analysis-specific open points (cost function/metric weighting) — see
  `analysis/CLAUDE.md`.
- Deployment mechanism repo → Raspi (script still to be built).
- Verify that the `speed` value sent via LIN (`raspi/control/motorcontrol.py`)
  actually corresponds to RPM — currently assumed, not confirmed against
  measured speed. Check once the Saleae Hall-edge speed measurement is
  working.
