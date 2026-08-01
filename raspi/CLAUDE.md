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

**Deploy target:** `/home/pi/auto/` — deliberately separate from the old
`/home/pi/LIN/` directory, which holds the pre-existing LIN bus code this
project's `raspi/control/` was originally copied from (kept there untouched
as reference, full of old test scripts and editor backups). `/home/pi/auto/`
is the clean deploy target for this repo's `raspi/` code going forward.

## Structure

- `control/` — LIN command code (`speed <value>` command, 0 = stop).
  Currently implemented as the LIN master itself (opens `/dev/ttyS0`
  directly). **Planned change** (see `watchdog/CLAUDE.md`'s Architecture
  section): the watchdog becomes the sole LIN master, and `control/`
  instead sends requests to it over local IPC — not yet done.
- `watchdog/` — Independent safety barrier, runs as its own process
  separate from the rest. See `watchdog/CLAUDE.md` for details — not here.

## LIN Protocol Timing

LIN on this hardware runs over a single-wire UART transceiver, which
echoes every transmitted byte back on RX. Every byte sent — sync, PID,
each data byte, checksum — must be followed by reading and discarding
that echo before sending the next byte, or the master falls out of sync
with the bus. `Lin.write()` and `Lin.read()` in `control/motorcontrol.py`
both do this correctly (write one byte, read one byte, repeat) and are
the only correct way to talk to the bus. All command functions
(`set_speed`, `led_on`, `led_off`, `get_hal`, `get_rpm`, `get_temp`) go
through these two methods — none of them should bypass `Lin.write()`/
`Lin.read()` with raw bulk `ser.write()` calls.

Earlier code (including the original `lincomm.py`'s `main()` CLI branches,
and an earlier version of this file's guidance) skipped the echo-read on
writes. That was wrong — it was inferred from an untested raw script, not
verified against real hardware, and contradicted `Lin.read()`'s own
(correct) pattern. Don't reintroduce a bulk-write-no-read shortcut.

This has not yet been verified against real hardware — do not treat "goes
through `Lin.write()`/`Lin.read()` consistently" as proof of correctness,
only as the best current understanding of the protocol.

## Open Points

- `control/motorcontrol.py` returns bare magic-number error codes
  (`-1`/`-2`/`-3`/`-4`) from `Lin.write()`/`Lin.read()`. Replace with named
  constants (or an enum) — deferred, planned for next session.

## Test Suite Policy

**Any change to `control/` or `watchdog/` must have the test suite run
against dry-run mode before the change is considered done** — see
`watchdog/CLAUDE.md`'s "Test Suite (Required on Every Change)" and
"Dry-Run Mode" sections for detail. No real hardware needed. Applies to
Claude Code too — don't deploy a change to either without running it.

## Motor Execution Consent

**Never run motor-control code on the Pi (or trigger it remotely) without the
user's explicit, in-the-moment consent — no exceptions, no assuming
permission from an earlier approval.** Deploying/copying code to the Pi is
fine on request; *executing* anything that can command the motor (e.g.
`motorcontrol.py speed ...`) requires the user to explicitly say so first,
every time.

## Security Note

Never place or commit private keys, passwords, or `known_hosts` contents
in this folder — see `.gitignore` at the repo root.
