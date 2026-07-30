# Auto — Automated BLDC Motor Test and Optimization Tool

## Goal

Autonomous optimization loop for a BLDC motor control algorithm on an
STM32 controller. A parameter set is built, flashed, the motor runs for a
test interval, the speed is measured, control metrics are computed from
that, and the next parameter set is derived from them.

## Machines/Devices Involved

- **STM32 host (Windows, this machine)**: Claude Code runs here.
  STM32CubeIDE/STM32_Programmer_CLI is installed here, and the Saleae
  Logic Pro 16 is also connected here.
- **STM32 controller**: Runs the control algorithm, drives the BLDC motor.
- **Raspberry Pi**: A pure execution node with no AI of its own. Sends
  LIN bus commands (Start/Stop/Speed) to the motor controller. Is
  remote-controlled by Claude Code over SSH (upload scripts, run them,
  read back results).
- **Saleae Logic Pro 16**: Records the motor's 3 Hall sensor channels
  plus a trigger channel. Handles speed measurement entirely — no more
  reading measurement data back over LIN.

## Data Flow / Control Channels

- **Control (LIN, already implemented):** Raspi → STM32 controller.
  Commands: motor start, motor stop, set speed.
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

## Safety

- **The watchdog on the Raspi (`raspi/watchdog/`) is independent of the
  optimization loop and of Claude Code.** It runs as its own process and
  stops the motor on its own if, e.g., no heartbeat/command arrives for
  too long. Limits (max speed, etc.) belong in the code, not in prompts
  or Claude-side discipline.
- A manual emergency-stop path must be triggerable at any time,
  independent of the loop.

## Repo Structure

```
Auto/
├── STM32/          Firmware + build/flash automation (STM32 CLI)
├── raspi/
│   ├── control/    LIN master code (Start/Stop/Speed) — already implemented
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

## Open Points / Still To Be Clarified

- Exact pin mapping (Hall channels, trigger pin) — fill in here once fixed.
- Saleae sample rate for Hall channels.
- Cost function/metric weighting for the optimization loop.
- Deployment mechanism repo → Raspi (script still to be built).
