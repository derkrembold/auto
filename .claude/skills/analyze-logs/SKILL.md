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
- Note if `--addresses` fell back to `None` (no `addresses.json`
  found) — the data-length check silently does nothing in that case,
  worth flagging so a truly clean report isn't mistaken for "checked
  and fine" when it was actually "not checked at all."
