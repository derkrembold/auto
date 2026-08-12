---
name: plot-step-response
description: Turn a capture_step_response.py or validate_speed.py CSV (elapsed_ms,rpm,current_val1,current_val2, optionally speed) into a dual-axis rpm+current PNG chart and send it to the user. Use when the user has run a step-response capture or speed-ramp validation and wants to see/visualize the result, or asks to plot/graph a capture/validate CSV.
---

Companion to `/run-raspi-validation` — that covers *running*
`capture_step_response.py`/`validate_speed.py`, this covers
*visualizing* what they produced. Both scripts share the same CSV shape
(see Parse below) so this one skill handles either. Read-only throughout
(no motor commands, no consent needed) except the one `scp` file copy in
step 1, which is also non-executing.

## 1. Locate and fetch the CSV

`capture_step_response.py` never writes a file itself (prints CSV to
stdout — see `raspi/CLAUDE.md`'s Structure section) — the user usually
redirected it into a file themselves, either locally or on the Pi. If
they just say "I made a capture.csv" without a path, check both:

```
ssh pi@motorpi.local "find / -maxdepth 4 -iname '*.csv' 2>/dev/null"
```

If it's on the Pi, copy it into the repo's `runs/` directory (create
the directory if needed):

```
scp pi@motorpi.local:/home/pi/auto/<name>.csv "runs/<date>_step_response_<from>_to_<target>.csv"
```

Match the existing naming convention in `runs/` (see the 2026-08-04 and
2026-08-10 captures already there) — infer `<from>`/`<target>` from the
data itself (first and settled rpm values) if the user doesn't say.

## 2. Parse

Base columns, both scripts: `elapsed_ms,rpm,current_val1,current_val2`.
`validate_speed.py` additionally has a `speed` column (commanded value
for that step — it's a multi-step ramp, not one fixed target).

- `capture_step_response.py`: current columns are **blank on most
  rows** — it only samples `current` once every
  `CURRENT_SAMPLE_INTERVAL` (default 1.0s, matches the current sensor's
  own on-board averaging window, see `currentsensor/CLAUDE.md`), not
  every `rpm` row. Skip blank cells when building the current series;
  don't treat them as 0 or interpolate.
- `validate_speed.py`: current is read once per step (every row) —
  `SETTLE_TIME` (default 3s) already exceeds the sensor's ~1s averaging
  window, so no blank cells to handle here.

## 3. Plot

matplotlib, dual y-axis (already installed on this machine — `pip
install matplotlib` if a fresh environment doesn't have it):

- x-axis: elapsed time in **seconds** (convert from `elapsed_ms`)
- left y-axis: `rpm` (every row) — line + small markers. Reference
  line(s) on this axis depend on which script produced the CSV: a
  single dashed horizontal line at the target speed for
  `capture_step_response.py` (one fixed target); a **step line** from
  the `speed` column for `validate_speed.py` (commanded value changes
  per row, so one constant reference line would be wrong)
- right y-axis (`ax1.twinx()`): `current_val1`/`current_val2` (only the
  rows where they're non-blank) — distinct markers/colors, since these
  points may be sparse relative to the rpm line
- combined legend (pull handles from both axes — `ax2.legend()` alone
  won't show `ax1`'s lines)
- title noting what was run (e.g. "speed 0 -> 1000" or "speed ramp
  validation") and the date

See the 2026-08-10 capture's plotting code (written inline that session,
not saved as a reusable script) for the exact pattern — reconstruct
similarly rather than assuming a script file exists to call.

## 4. Save and send

Save as a PNG sibling to the CSV in `runs/`, same basename
(`runs/<date>_step_response_<from>_to_<target>.png`). Send it with
`SendUserFile` (`display: "render"` so it shows inline) — don't just
describe the plot in text.

## 5. Worth a one-line summary

After sending, a short text summary of what the data shows (dead
time/rise time on the rpm side, settled current draw) is useful — see
past captures for the level of detail (e.g. "~1s dead time before the
motor starts moving, settles around 1000 rpm by ~2s, current settles
around -0.5 to -0.6A while running").
