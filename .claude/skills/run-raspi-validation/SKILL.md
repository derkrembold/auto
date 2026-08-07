---
name: run-raspi-validation
description: Run a real-hardware validation script on the Pi (validate_speed.py, validate_motor_currentsensor.py, or capture_step_response.py) — pre-flight checks, consent gating, and where to save the output. Use when the user asks to run a speed validation, bus-coexistence check, step-response capture, or similar motor-behavior test.
---

Covers `raspi/control/validate_speed.py`,
`raspi/control/validate_motor_currentsensor.py`, and
`raspi/control/capture_step_response.py` — same pre-flight/consent
mechanics, only the script name differs. See `raspi/CLAUDE.md`'s
Structure section for what each script actually does.

## 1. Pre-flight check (read-only, no consent needed)

```
ssh pi@motorpi.local "pgrep -af watchdog.py; echo '---'; lsof /tmp/motorwatchdog.sock 2>&1"
```

- **Watchdog not running (`--live`):** don't start it yourself. Starting
  `watchdog.py --live` enables real bus access and needs the same
  explicit, in-the-moment consent as any motor command (see
  `raspi/watchdog/CLAUDE.md`'s Dry-Run Mode section — the `--live` flag
  is the thing consent gates, not a formality). Ask the user first, as
  a separate consent event from running the validation script itself.
- **A client is already connected** (an `lsof`/`ss` entry on
  `/tmp/motorwatchdog.sock` beyond the watchdog process's own listening
  socket — e.g. someone's `motorcontrol.py` session left open): don't
  try to force past this. The watchdog serves one client at a time (see
  `raspi/watchdog/CLAUDE.md`'s Connection Model) — a second connection
  attempt just hangs waiting for the first to close, it doesn't fail
  cleanly. Tell the user and ask them to close the other session first.

## 2. Consent, then run

Running either script issues real `speed` commands — needs explicit,
in-the-moment consent every time, same as flashing or any other motor
action (see `raspi/CLAUDE.md`'s Motor Execution Consent section). Ask
immediately before running, regardless of earlier approvals in the same
conversation.

```
ssh pi@motorpi.local "cd /home/pi/auto && python3 validate_speed.py"
ssh pi@motorpi.local "cd /home/pi/auto && python3 validate_motor_currentsensor.py"
ssh pi@motorpi.local "cd /home/pi/auto && python3 capture_step_response.py"
```

All three scripts already end with `speed 0`, so the motor is stopped when
they return normally. If a run is interrupted (Ctrl+C, connection drop),
the watchdog's own disconnect handling stops the motor independently —
see `raspi/watchdog/CLAUDE.md`'s Connection Model.

## 3. Save the output

None of the scripts write a file themselves — all print to stdout and
leave saving up to the caller. For `capture_step_response.py`'s CSV
(`elapsed_ms,rpm` rows), save the captured stdout into `runs/` in the
main repo (not on the Pi), named
`runs/<date>_step_response_<from>_to_<target>.csv`. If a plot is useful,
matplotlib works locally (`pip install matplotlib` if not already
present) — see the 2026-08-04 run for the plotting pattern used
(elapsed seconds on x, rpm on y, target-speed reference line), save as
a sibling `.png` next to the CSV, and send it with `SendUserFile`.
`validate_speed.py`'s and `validate_motor_currentsensor.py`'s output is
normally just reported in the conversation, not saved as a file, unless
the user asks for that too.

If the STM32CubeIDE version or the Pi's deploy path changes, adjust the
paths above accordingly — see `raspi/CLAUDE.md`'s Access section for the
current hostname/deploy target.
