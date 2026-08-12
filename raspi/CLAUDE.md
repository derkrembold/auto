# raspi — Context for Claude Code

This folder contains the code that runs on the Raspberry Pi. The Pi itself
is a pure execution node with no git checkout of its own — development and
versioning happen here in the repo, deployment happens via SCP/SSH.

## Access

- **Hostname:** `motorpi.local` (mDNS — usable on the local network,
  independent of a changing IP)
- **User:** `pi`
- **Auth:** SSH key (ed25519), passwordless. Key lives at
  `C:\Users\rembo\.ssh\id_ed25519` — **not** inside this repo.
- There is a second Raspberry Pi on the same network — do not confuse
  them. Only `motorpi.local` is the motor controller Pi.

Connection test:
```
ssh pi@motorpi.local
```
Should log in directly without a password prompt.

## Deployment Pattern

Code from `raspi/control/` resp. `raspi/watchdog/` is pushed to the Pi via
`scp`/`rsync`, executed there, and results/logs are read back. No manual
editing of code directly on the Pi — always make changes here in the repo,
then redeploy, so the repo and the actual state on the Pi don't drift
apart.

**Use `raspi/deploy.sh`** (or the `/deploy-raspi` skill, which just runs
it) rather than hand-picking `scp` commands — it's the one place that
knows the correct file list and the `CLAUDE.md` naming-collision gotcha
below. Copy-only, never executes anything on the Pi.

**Deploy target:** `/home/pi/auto/` — deliberately separate from the old
`/home/pi/LIN/` directory, which holds the pre-existing LIN bus code this
project's `raspi/control/` was originally copied from (kept there untouched
as reference, full of old test scripts and editor backups). `/home/pi/auto/`
is the clean deploy target for this repo's `raspi/` code going forward.

**Flat directory, watch for name collisions:** all `raspi/*` source files
deploy into that one flat directory (needed for `linaddresses.py` to be
importable by both `control/` and `watchdog/` code without cross-folder
import machinery). This already collided once: `raspi/CLAUDE.md` and
`raspi/watchdog/CLAUDE.md` are both named `CLAUDE.md` — deploy the
watchdog one as `watchdog-CLAUDE.md` to avoid silently overwriting the
other. Same caution applies to any future same-named files across
`raspi/` subfolders.

## Structure

- `control/motorcontrol.py` — small interactive CLI (`speed <value>`
  command, 0 = stop, plus `on`/`off`/`hal`/`rpm`/`temp`/`current`,
  `help`, `exit` to quit). `current` reads the current sensor board's two
  ACS712xLCTR-20A chips (one per motor — see `currentsensor/CLAUDE.md`'s
  Hardware section) via `linbus.get_current()`: `val1`/`val2` are amps,
  converted from the raw 10-bit ADC reading on this (Raspi) side, not on
  the AVR — see `linbus.py`'s `_adc_to_amps()`/`ACS712_*` constants
  (Vcc=5V, 2.5V=0A confirmed against hardware, 100mV/A per the
  ACS712xLCTR-**20A** datasheet). Its
  firmware doesn't read its own instance-strap pins yet either (unlike
  the motor's `hwbits`, see `watchdog/CLAUDE.md`'s `linbus.py` constants)
  so it's addressed at instance 0 for now — fine while only one physical
  sensor exists. This is a manual/CLI read only, not wired into the
  watchdog's stall-check safety logic (see `watchdog/CLAUDE.md`'s
  Two-Layer Safety Check section — that integration is still open,
  deliberately deferred until the sensor's readings are trusted).
  Arrow-key command history via `readline` (Unix/Pi only,
  import is guarded so it doesn't break local Windows testing). Holds
  one persistent IPC connection to the watchdog for the whole session —
  does **not** open `/dev/ttyS0` itself, no `RPi.GPIO`/`serial`
  dependency at all. See `watchdog/CLAUDE.md`'s Connection Model section
  for why it's persistent (instant disconnect detection) rather than
  reconnecting per command. Logs every command/reply to `motorcontrol.log`
  (also echoed live to the terminal) via the shared `control/logsetup.py`
  — see `watchdog/CLAUDE.md`'s log-format section for the full design
  (rotation, why the file always has full detail).
- `control/logsetup.py` — shared logging setup (`logsetup.configure()`)
  used by all four `raspi/` scripts below and by `watchdog/watchdog.py`.
  Rotating log file per script (one generation kept as `<name>.log.1`),
  always full detail in the file, independently-leveled optional
  terminal echo. See `watchdog/CLAUDE.md`'s log-format section — that's
  where the design reasoning lives, not duplicated here.
- `control/validate_speed.py` — standalone script implementing the
  speed-ramp validation sequence from root `CLAUDE.md`'s Open Points
  (0 → 400 → 800 → 1200 → 800 → 400 → 0 → -400 → -800 → -1200 → -800 →
  -400 → 0, checking `rpm` and `current` after every step — `current`
  read once per step, not on a separate schedule, since `SETTLE_TIME`
  (3s default) already exceeds the current sensor's ~1s on-board
  averaging window). Prints CSV
  (`elapsed_ms,speed,rpm,current_val1,current_val2`) to stdout — same
  shape `/plot-step-response` already knows how to plot, plus a `speed`
  column since this is a multi-step ramp, not one fixed target. Not a
  pytest test case (real hardware, see Test Suite Policy below) — run it
  directly (`python3 validate_speed.py`) with the watchdog already
  running `--live`. Falls under Motor Execution Consent below like any other
  motor command, whether run manually on the Pi or triggered remotely.
  Uses one persistent connection for the whole sequence (imports
  `SOCKET_ADDRESS` from `motorcontrol.py`), deliberately not the
  one-shot `send_command()` helper — a one-shot connection's immediate
  disconnect would trigger the watchdog's stop-on-disconnect after every
  single step. Every command/reply also logged to `validate_speed.log`
  (file only, not echoed to the terminal — stdout is reserved for the
  CSV stream above).
- `control/validate_motor_currentsensor.py` — standalone script
  regression-testing motor+currentsensor bus coexistence: steps speed
  through `[0, 500, 1000, 500, 0]`, and after each step (following a
  `SETTLE_TIME` pause) sends `current`, `hal`, `rpm` in turn. Built
  2026-08-07 specifically to catch the LIN receive-state-machine hang
  found that day — STM32's `HAL_UART_RxCpltCallback` didn't re-arm UART
  reception for a recognized-but-foreign pid (`st0cur`, when `current`
  is queried while the motor is running) — see `STM32/CLAUDE.md`/
  `currentsensor/CLAUDE.md` for the fix on both sides. Same one-
  persistent-connection and Motor Execution Consent reasoning as
  `validate_speed.py` above.
- `control/capture_step_response.py` — standalone script: `speed 0` →
  `speed 1000` (step input), then samples `rpm` every 200ms for 8s
  (measured from the step, not from the initial `speed 0`), always
  ending with `speed 0`. Prints CSV
  (`elapsed_ms,rpm,current_val1,current_val2`) to stdout — does not
  write a file itself, the caller (human or Claude capturing the SSH
  output) decides where it's saved, e.g. `runs/` in the main repo (see
  root `CLAUDE.md`'s Repo Structure). `current` is sampled at its own,
  much slower `CURRENT_SAMPLE_INTERVAL` (default 1.0s, not every 200ms
  row) — the current sensor's own on-board averaging window is ~1s (see
  `currentsensor/CLAUDE.md`'s `countmax`/`OCR1A` tuning), so sampling it
  faster would just re-read the same averaged value; `current_val1`/
  `current_val2` are blank on rows where it wasn't sampled that tick.
  Same one-persistent-connection and Motor Execution Consent reasoning
  as `validate_speed.py` above. Sampling is scheduled against the
  absolute start time (not accumulated sleeps) so per-sample LIN
  round-trip latency doesn't drift the interval over the run. Every
  command/reply also logged to `capture_step_response.log` (file only,
  same stdout-stays-clean-for-CSV reasoning as `validate_speed.py`).
  Both this and `validate_speed.py` above have their pre-flight checks
  (watchdog running? client already connected?), consent gating, and
  output-saving convention written up once in the `/run-raspi-validation`
  skill — use that instead of re-deriving the steps each time. Once a
  capture CSV exists, `/plot-step-response` turns it into a dual-axis
  rpm+current PNG chart.
- `analyze_logs.py` — read-only static analysis over the four `.log`
  files above (built 2026-08-12, together with the `/analyze-logs`
  skill): flags unmatched `->` calls (the 2026-08-11 bus-hang
  signature), non-zero `ret` codes, calls exceeding a fixed latency
  threshold, `data=[...]` lengths that don't match `addresses.json`'s
  `bytes` field, `WARNING`/`ERROR` lines (via the log level field), and
  watchdog poll-loop cadence gaps. Not deployed to the Pi — runs
  locally against fetched log copies (e.g. in `runs/`), no consent
  needed. See its own docstring and `watchdog/CLAUDE.md`'s log-format
  section for the exact checks and line-format details.
- `watchdog/` — Independent safety barrier, runs as its own process
  separate from the rest, and is the sole LIN master (owns
  `/dev/ttyS0` — `control/` no longer does). See `watchdog/CLAUDE.md`
  for details, including `linbus.py` (the `Lin` class + command
  functions, moved there from `control/motorcontrol.py`).

## LIN Protocol Timing

LIN on this hardware runs over a single-wire UART transceiver, which
echoes every transmitted byte back on RX. Every byte sent — sync, PID,
each data byte, checksum — must be followed by reading and discarding
that echo before sending the next byte, or the master falls out of sync
with the bus. `Lin.write()` and `Lin.read()` in `watchdog/linbus.py`
(moved there from `control/motorcontrol.py` during the sole-LIN-master
restructuring — see `watchdog/CLAUDE.md`) both do this correctly (write
one byte, read one byte, repeat) and are the only correct way to talk
to the bus. All command functions (`set_speed`, `led_on`, `led_off`,
`get_hal`, `get_rpm`, `get_temp`), also in `linbus.py`, go through
these two methods — none of them should bypass `Lin.write()`/
`Lin.read()` with raw bulk `ser.write()` calls.

Earlier code (including the original `lincomm.py`'s `main()` CLI branches,
and an earlier version of this file's guidance) skipped the echo-read on
writes. That was wrong — it was inferred from an untested raw script, not
verified against real hardware, and contradicted `Lin.read()`'s own
(correct) pattern. Don't reintroduce a bulk-write-no-read shortcut.

**Verified against real hardware (2026-08-03):** both directions
confirmed working live via `watchdog.py --live` — `hal` (`Lin.read()`)
read the Hall sensors, and `speed` (`Lin.write()`) actually turned the
motor, with `rpm` (`Lin.read()`) reading plausible values while it
spun. `on`/`off` (also `Lin.write()`, same code path as `speed`) not
separately tested but share the exact same write logic. The echo/
parity/checksum handling in both `Lin.write()` and `Lin.read()` is now
real-hardware-confirmed, not just "best current understanding."

## Open Points

- `watchdog/linbus.py` returns bare magic-number error codes
  (`-1`/`-2`/`-3`/`-4`) from `Lin.write()`/`Lin.read()`. Replace with named
  constants (or an enum) — deferred.
- **`validate_speed.py`/`capture_step_response.py` silently swallow
  `ret!=0` reads** (2026-08-12, part of the bus-hang investigation — see
  `STM32/CLAUDE.md`'s Open Points): `_read_rpm()`/`_read_current()`'s
  regex just fails to match on a `None`/error reply, so the row prints
  literal `"None"` in the CSV instead of raising an alarm — easy to miss
  live, only visible on close inspection of the output afterward. Should
  flag conspicuously (or abort) on `ret!=0`, similar to
  `validate_motor_currentsensor.py`'s `_invalid_current_reason()` sanity
  check. Not yet built — planned alongside the STM32/currentsensor error
  counters for the same investigation.

## Test Suite Policy

**Any change to `control/` or `watchdog/` must have the test suite
(`pytest raspi/tests/`) run before the change is considered done** — see
`watchdog/CLAUDE.md`'s "Test Suite (Required on Every Change)" and
"Dry-Run Mode" sections for detail. Applies to
Claude Code too — don't deploy a change to either without running it.

**Test suite ≠ validation — don't conflate them.** The pytest suite
checks *code logic* against dry-run/mocks, no real hardware, no consent
needed, fast and repeatable. *Validation* checks whether the *real
system* (motor, firmware, LIN bus) actually behaves as assumed — needs
real hardware, falls under Motor Execution Consent below, isn't
automatable the same way. E.g. the speed-ramp validation sequence in
root `CLAUDE.md`'s Open Points is validation, not a test case that
belongs in `raspi/tests/`.

## Motor Execution Consent

**Never run motor-control code on the Pi (or trigger it remotely) without the
user's explicit, in-the-moment consent — no exceptions, no assuming
permission from an earlier approval.** Deploying/copying code to the Pi is
fine on request; *executing* anything that can command the motor (e.g.
`motorcontrol.py speed ...`) requires the user to explicitly say so first,
every time.

Code-level reinforcement of this, not a substitute for it: `watchdog.py`
defaults to dry-run (`DryRunLin`, no real bus access at all) unless
started with an explicit `--live` flag — see `watchdog/CLAUDE.md`'s
Dry-Run Mode section. Running `watchdog.py` without `--live` is safe
regardless of consent; running it *with* `--live` still needs consent
every time, the flag doesn't change that.

## Security Note

Never place or commit private keys, passwords, or `known_hosts` contents
in this folder — see `.gitignore` at the repo root.
