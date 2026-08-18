---
name: plot-saleae-step-response
description: Overlay a capture_step_response.py CSV's LIN-reported rpm against a Saleae capture's Hall-edge-derived rpm (ground truth), plus the LIN current draw on a second axis, auto-aligned via the trigger pin. Use when the user has both a step-response CSV and a Saleae export from the same run and wants to compare/sanity-check them, or asks to overlay/merge Hall and LIN rpm data.
---

Companion to `/plot-step-response` (LIN data only) and
`analysis/hall_rpm.py` (Saleae Hall-edge -> rpm conversion) — this
combines both into the overlay plot built ad hoc for
`runs/2026-08-17_trigger_pin_test4/` and
`runs/2026-08-18_trigger_capture/` before this skill existed. Also the
same overlay `saleae-trigger-capture`'s own Analyze step produces
internally for captures it takes itself — use *this* skill instead when
the two inputs already exist independently (e.g. a manually-run
`capture_step_response.py` plus a separately-taken Saleae capture) and
weren't produced together by that skill. Read-only throughout — no
motor commands, no consent needed.

## 1. Locate both inputs

- The `capture_step_response.py` CSV (`elapsed_ms,rpm,current_val1,current_val2`
  — see `/plot-step-response`'s step 1 for fetching it from the Pi if
  it's not already local).
- The Saleae export directory containing `digital.csv` (under
  `saleae/exports/<name>/`, produced by `saleae_mcp/server.py`'s
  `export_capture()`).

If the user only gives one, ask which capture pairs with it rather than
guessing — nothing here can infer that two files belong to the same run
just from timestamps.

## 2. Auto-align the two clocks

The two files have independent clocks (the CSV's `elapsed_ms` starts at
the `speed <target>` command; the Saleae's is capture-relative to
whenever the capture itself started). Don't assume they're already
aligned or ask the user to align them by hand — the trigger pin's
rising edge (`cntl3mot`'s speed-nonzero write) is the same LIN
transaction as `elapsed_ms=0`, so it's a reliable shared t=0 in both
`timed`- and `trigger`-mode captures:

```python
from analysis.hall_rpm import find_sustained_high_edge

trigger_t = find_sustained_high_edge(digital_csv_path)  # None if not found
```

- `trigger` mode: `trigger_t` comes back ~0 (the capture already starts
  at the trigger) — confirmed 2026-08-18.
- `timed` mode: `trigger_t` is wherever in the capture window the pin
  actually went high (e.g. 4.035s into a 20s window) — confirmed
  2026-08-17.
- If `trigger_t` is `None`: the trigger channel never held HIGH for
  ≥0.5s in this capture — likely the wrong export, or a capture that
  didn't actually cover a real motor run (see `saleae/CLAUDE.md`'s
  Trigger pin Open Point for the false-trigger case this also catches).
  Stop and tell the user rather than plotting misaligned data.

Shift every Saleae timestamp by `-trigger_t` before plotting, so both
series share the "seconds since the speed command" x-axis.

## 3. Compute both rpm series, plus current

```python
from analysis.hall_rpm import hall_rpm_from_csv

hall_t, hall_rpm = hall_rpm_from_csv(digital_csv_path, bin_s=0.1, t0=0.0)
hall_t = [t - trigger_t for t in hall_t]
```

LIN rpm series: parse the CSV directly (`elapsed_ms` -> seconds, `rpm`
column). Current (added 2026-08-18, same source as `/plot-step-response`'s
step 2): `current_val1`/`current_val2` columns — **blank on most
rows**, `capture_step_response.py` only samples `current` once every
`CURRENT_SAMPLE_INTERVAL` (default 1.0s, see `raspi/CLAUDE.md`'s
Structure section), not every `rpm` row. Skip blank cells when building
the current series, don't treat them as 0 or interpolate — same
handling as `/plot-step-response`. The Saleae capture has no current
data of its own (it only taps the Hall/trigger digital lines, see root
`CLAUDE.md`'s Data Flow section) — current only ever comes from the LIN
side.

## 4. Plot and send

matplotlib, dual y-axis:
- Left axis (rpm): LIN rpm via `ax.step(..., where="mid")` — it's a
  ~200ms-polled, 25-quantized value, a step line reflects that
  honestly (see `STM32/CLAUDE.md`'s RPM Measurement Resolution section
  for why it's quantized — not noise); Hall rpm via
  `ax.plot(..., marker=".")` — continuous ground truth; dashed
  horizontal reference line at the commanded target speed.
- Right axis (`ax.twinx()`): `current_val1`/`current_val2` as
  connected lines (not scatter — sparse in time but still meaningfully
  a trend), distinct markers/colors, built only from the rows where
  they're non-blank (sparse relative to the rpm lines).
- Combined legend — pull handles from both axes (the right axis's
  `legend()` alone won't show the left axis's lines, same gotcha
  `/plot-step-response` documents).
- Title noting the run and date, grid.

Save as PNG into `runs/<date>_<name>/`, send with `SendUserFile`
(`display: "render"`). See
`runs/2026-08-18_trigger_capture/plot_trigger_capture.py` for the rpm
overlay pattern and `/plot-step-response`'s step 3 for the dual-axis
current pattern to combine it with.

## 5. Report

State the alignment point used (`trigger_t`) and whether the two series
agree, same sanity check as `analysis/CLAUDE.md`'s Hall-Edge RPM
Conversion section describes (ramp-up/steady-state/coast-down should
track closely; the LIN series will show more jitter from its 25-rpm
quantization, that's expected, not a discrepancy).
