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
  command, 0 = stop, plus `on`/`off`/`hal`/`rpm`/`temp`, `help`, `exit`
  to quit). Arrow-key command history via `readline` (Unix/Pi only,
  import is guarded so it doesn't break local Windows testing). Holds
  one persistent IPC connection to the watchdog for the whole session —
  does **not** open `/dev/ttyS0` itself, no `RPi.GPIO`/`serial`
  dependency at all. See `watchdog/CLAUDE.md`'s Connection Model section
  for why it's persistent (instant disconnect detection) rather than
  reconnecting per command.
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
