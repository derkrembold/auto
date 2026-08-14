---
name: analyze-logs
description: Fetch watchdog.log/motorcontrol.log/validate_speed.log/capture_step_response.log from the Pi and run raspi/analyze_logs.py over them to check for LIN bus hangs, non-zero ret codes, slow calls, data-length mismatches, WARNING/ERROR lines, and watchdog poll-loop cadence gaps. Use after a real-hardware run when the user wants the logs checked for problems, or asks to analyze/check the logs.
---

Companion to `/plot-step-response` — that visualizes CSV *data*, this
checks the *protocol-level log traces* for problems (see
`raspi/watchdog/CLAUDE.md`'s log-format section for what the logs
themselves look like, and `raspi/analyze_logs.py`'s own docstring for
the exact checks). Read-only throughout — no motor commands, no
consent needed.

## 1. Fetch the logs

Whichever of the four log files are relevant to what the user ran
(usually all four — `watchdog.log`, `motorcontrol.log`,
`validate_speed.log`, `capture_step_response.log`; `.log.1` files exist
too if the prior generation matters). Fetch each individually with its
own `scp` call — **don't** use brace-expansion in the remote path
(`{a,b,c}`), it doesn't get shell-expanded by `scp` and fails outright.
`motorpi.local` mDNS resolution is known to fail intermittently
(especially across repeated calls in one script/loop) — retry
individually on failure rather than assuming a fetch that came back
empty means the file doesn't exist on the Pi.

```
scp pi@motorpi.local:/home/pi/auto/watchdog.log "runs/<date>_logs/"
```

Save into `runs/<date>_logs/` (create if needed), matching the
convention already used for prior log-review sessions.

## 2. Run the analyzer

```
python3 raspi/analyze_logs.py runs/<date>_logs/*.log
```

Run from the repo root so the default `--addresses` auto-detection
(repo-root `addresses.json`, relative to `raspi/analyze_logs.py`'s own
location) finds the file without needing to pass it explicitly. Exit
code is `0` if every given file came back clean, `1` if any finding was
raised in any file — useful as a first signal before reading the
printed report.

## 3. Report back

- **All clean:** a short confirmation is enough — which files, call
  counts, no need to reproduce the full "no anomalies found" report
  verbatim per file.
- **Findings present:** summarize what was found and where (file +
  line number + one-line cause), don't just paste the raw tool output
  — but do keep enough detail (exact `ret` code, exact byte counts,
  exact timestamps) that the user can jump to the right log line
  without rerunning anything themselves. If a finding looks like the
  known 2026-08-11 bus-hang signature (an `unmatched` finding on a
  `[poll]`/`[client]` linbus read) say so explicitly — that's the
  specific failure mode this whole logging system was built to catch.
- **Known expected signature, not a bug: `selftest`'s deliberate
  provocations (added 2026-08-13/14).** Every time `motorcontrol.py`'s
  `selftest` command runs, its `bushang_test` part *deliberately*
  breaks one `st0cur` read on purpose (arms currentsensor's
  `sabotageNextReply` via a `write cntl0cur data=['0xfa', '0x17']`
  line, then triggers a `current` read) — this always shows up as a
  `ret_nonzero` (`ret=-5`), a `latency` (~2s), and a `length` (1 byte
  instead of 4) finding for that one `st0cur` call, every single time,
  on a working system. Recognize it by the `write cntl0cur
  data=['0xfa', '0x17']` line immediately preceding the failing
  `st0cur` call — report it as "expected, `selftest`'s own bus-hang
  provocation, not a bug" rather than as an unexplained anomaly. Don't
  confuse this with the 2026-08-11 signature above — this one always
  resolves (a `ret=-5`/`length` finding, not `unmatched`); an
  `unmatched` finding anywhere near a `selftest` run would still mean
  the STM32 failed to recover and is the real bug the fix (see
  `STM32/CLAUDE.md`'s Status section) is supposed to prevent.
  `selftest`'s `checksum_test` part (a `write cntl3mot ... (DELIBERATELY
  BAD CHECKSUM)` line) is quieter — it doesn't itself produce a finding
  (the corrupted write gets no reply, by LIN design), so nothing needs
  explaining away there.
- Note if `--addresses` fell back to `None` (no `addresses.json`
  found) — the data-length check silently does nothing in that case,
  worth flagging so a truly clean report isn't mistaken for "checked
  and fine" when it was actually "not checked at all."
