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
  command, 0 = stop, plus `pi <p_delta> <i_delta>`/`hal`/`rpm`/`temp`/
  `current`/`errors`, `help`, `exit` to quit). `pi` (replaced the
  on/off status-LED toggle 2026-08-18, same `cntl0mot` PID and
  checksum-gate, see `STM32/CLAUDE.md`'s Motor Control section and
  `watchdog/CLAUDE.md`'s `linbus.set_pi()`) sets `KP`/`KI` for
  `picontrol()`'s PI controller as `firmware_default + delta` — always
  relative to the hardcoded default, never cumulative against whatever
  is currently applied, so repeated calls (or a grid/gradient search
  loop) never drift and don't need to track prior state. Each delta is
  a signed byte ×100 on the wire (`PI_DELTA_MIN`/`MAX` in
  `watchdog.py`, -1.28..1.27) — not calling `pi` at all leaves both
  gains at their firmware defaults (`KPDEFAULT`/`KIDEFAULT` in
  `main.c`). **Confirmed on real hardware (2026-08-19)** — see
  `STM32/CLAUDE.md`'s Commutation & Control section for the specific
  boundary-value test evidence from that day's log check. `errors`
  (added 2026-08-12) reads
  the currentsensor's `st1cur` — its last 8 error codes (most recent
  first, `currentsensor/firmware/main.cpp`'s `errorstorage` ring
  buffer), decoded via `linbus.get_error_history()`/
  `CURRENTSENSOR_ERROR_NAMES` into both raw codes and names (`SYN`/
  `PAR`/`PID`/`MSI`/`CHK`/`TIM`/`IND`/`NUM`, mirroring
  `currentsensor/firmware/errors.hpp`). Currentsensor-only — the motor
  side has no equivalent error-*history* ring buffer (its `st3mot` is a
  single running counter for a different, specific purpose, see
  `selftest` below). Deliberately
  **not** auto-triggered by a failed `current` read — kept as its own
  explicit, manually-invoked command (discussed 2026-08-12): automatic
  follow-up queries would make `current`'s behavior context-dependent
  and harder to predict/test, and conflicts with this project's general
  preference for explicit over implicit bus activity (e.g.
  `poll_current()`'s observe-only stall signature, below).

  `selftest` (added 2026-08-13, extended 2026-08-13/14/15) does the
  following in one call, ~2s total:
  1. Exercises the currentsensor's `cntl0cur` test hook end to end via
     `linbus.currentsensor_selftest()`: injects a known non-zero pattern
     into `errorstorage` (`0x01`/`0xab`), reads it back via `st1cur`,
     resets it to zero (`0xcd`/`0x0c`), reads it back again. Piggybacks
     on `cntl0cur`'s pre-existing LED-test bytes rather than a dedicated
     pid — deliberate, discussed 2026-08-13: the only caller is this
     project's own `motorcontrol.py`, so the coupling (LED test and
     errorstorage inject/reset always happening together) has no real
     cost.
  1.5. (Added 2026-08-15) Deliberately provokes currentsensor's
     `cntl0cur` checksum gate (`main.cpp` — see `currentsensor/CLAUDE.md`'s
     Status section for the bug this fixed): sends the *inject* bytes
     (`[0x01,0xab]`) with a deliberately wrong checksum via
     `linbus.provoke_currentsensor_checksum_error()` /
     `Lin.write_bad_checksum()`. Reads `st1cur` before/after — expects
     `errorstorage[0]==-5` (CHK, logged unconditionally either way) but
     critically `errorstorage[1]==0`, not `0x11` (proves the inject
     action was actually *skipped*, not just that a mismatch was noted —
     stronger than detection-only). Also reads `st3mot`
     (`linbus.get_motor_counters()`) before/after to confirm the STM32's
     own counters stay completely unchanged — this message is addressed
     to the currentsensor, not the motor, so the STM32's `is_our_write`
     scoping should exclude it even though it still tracks the frame on
     the shared bus. Uses the inject bytes specifically, not the reset
     bytes — reset's effect (zero everything) would be indistinguishable
     from "already zero" and wouldn't actually prove anything.
     **Confirmed against real hardware (2026-08-15):** run twice
     (`runs/2026-08-15_cs_checksum_test/`), both times `errorstorage[1]`
     stayed `0` and both STM32 counters stayed flat, while the other two
     parts below moved only their own respective counter — all three
     provocations confirmed mutually isolated.
  2. Deliberately reproduces, on demand, the 2026-08-11 STM32 bus-hang
     scenario and confirms both sides actually caught it
     (`linbus.provoke_bus_hang_timeout()`, see `STM32/CLAUDE.md`'s and
     `currentsensor/CLAUDE.md`'s Status sections for the full story):
     arms a `cntl0cur [0xfa,0x17]` sabotage flag on the currentsensor
     that forces its next `st0cur`/`st1cur` reply to abort after 1 byte,
     triggers a real `st0cur` read to fire it (this read times out,
     `ret=-5`, expected), then reads `st3mot` (`linbus.get_motor_counters()`
     — the STM32's `HAL_GetTick()` bus-hang-timeout counter,
     `bodyTimeoutCount`) and `st1cur` before/after to confirm both
     incremented/logged the event.
     Confirmed against real hardware repeatedly, motor both idle and
     running — see the CLAUDE.md sections above.
  3. (Added 2026-08-14) Deliberately provokes the STM32's `checksum_ok`
     gate (`main.c`'s main-loop dispatch on `cntl0mot`/`cntl1mot`/
     `cntl2mot`/`cntl3mot` — see `STM32/CLAUDE.md`): sends a `cntl3mot`
     (speed) write with a deliberately wrong checksum via
     `linbus.provoke_checksum_error()`, value fixed at 0 so it's safe to
     call without Motor Execution Consent even if the gate were broken.
     Reads `st3mot`'s `checksumErrorCount` before/after to confirm it
     went up by exactly 1. Detection-only — doesn't itself prove the
     motor's setpoint stayed unchanged; a direct `rpm`-based before/after
     check with a real nonzero speed would need its own, separately
     consent-gated command, not yet built. **Confirmed against real
     hardware (2026-08-14):** run twice, motor idle and running at 500 —
     `checksumErrorCount` went up by exactly 1 both times, independent
     of the `bushang_test` part's own `bodyTimeoutCount` counter (which
     kept climbing on its own, `checksum` stayed flat during that part).
     See `STM32/CLAUDE.md`'s Status section for the full readout,
     including an incidental `rpm`-trace confirmation that the rejected
     write had no effect on the actual setpoint.

  `current` reads the current sensor board's two
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

  **Optional `--p-delta`/`--i-delta` (added 2026-08-19):** if given
  (both or neither), sends `pi <p_delta> <i_delta>` as the very first
  command, before `speed 0` — see the `pi` command entry above.
  Deliberately no client-side range re-check here; a rejected `pi`
  (the watchdog's own `validate()` is the single source of truth for
  the -1.28..1.27 range) aborts via `sys.exit()` before the motor is
  touched at all. This is what `run_experiment.py` (repo root) uses to
  set a grid/gradient-search point before capturing its step response
  — see that script's own docstring.
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
to the bus. All command functions (`set_speed`, `set_pi`,
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
spun. `pi` (also `Lin.write()`, same code path as `speed`) not
separately tested but shares the exact same write logic. The echo/
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
