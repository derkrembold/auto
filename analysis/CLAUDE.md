# analysis — Context for Claude Code

This folder turns raw Saleae captures into speed data and control-quality
metrics for the optimization loop described in the root `CLAUDE.md`.

## Purpose

- Compute instantaneous motor speed from Saleae Hall-edge captures
  (`saleae/exports/`) — time between edge transitions on the 3 Hall
  channels.
- Derive control-quality metrics/cost from a run's speed trace, used to
  produce the next parameter set in the optimization loop.

## Hall-Edge RPM Conversion

**First real Hall-edge-to-rpm conversion done and cross-checked against
LIN `rpm` (2026-08-17).** Formula matches the STM32 firmware's own
`RPMFACTOR` derivation exactly (see `STM32/CLAUDE.md`'s RPM Measurement
Resolution section): 24 Hall edges (single-bit Gray-code transitions,
summed across all 3 Hall channels) = 1 mechanical revolution, so
`rpm = (edge_count_in_window / 24) * (60 / window_seconds)`. Binning the
edge count into 100ms windows (matching the firmware's own `SAMPLERATE`)
gives a directly comparable trace.

**Real-hardware confirmation:** a Saleae capture during a live
`capture_step_response.py` run (`saleae/exports/
step_response_trigger_test4/`, see `STM32/CLAUDE.md`'s trigger-pin
Status entry) converted this way tracks the LIN-reported `rpm` closely
across the whole ramp-up/steady-state/coast-down — see
`runs/2026-08-17_trigger_pin_test4/hall_vs_lin_rpm.png` and the script
that produced it, `runs/2026-08-17_trigger_pin_test4/
plot_hall_vs_lin_rpm.py` (one-off so far, not yet promoted into a
proper `analysis/` module — see Open Points). Timeline alignment
between the two independent sources (Saleae capture-relative time vs.
the Raspi's wall-clock command log) used the trigger pin's own rising
edge as the shared t=0, since that edge and the `cntl3mot` write it's
driven by are the same LIN transaction.

**Raw Hall signal noise — found and filtered, not a firmware bug.**
About half of the raw capture's edge-count rows were single-sample-wide
spikes (~100ns at the 10MHz digital sample rate) that revert
immediately — electrical ringing/EMI picked up on the Hall lines during
MOSFET commutation, not real state changes (confirmed via the
inter-transition gap distribution: genuine transitions cluster around
~200-400µs at this rpm, spikes are exactly one sample period). Naively
counting every CSV row as an edge overshoots computed rpm by roughly
3.5x. Fixed with a simple debounce: any segment shorter than 1µs is
merged into its predecessor before counting transitions. This is a
property of the raw high-bandwidth digital capture, not evidence of a
problem in the firmware's own Hall counting (`hallCounter`, incremented
via `stm32h7xx_it.c`'s EXTI handler) — the firmware's `rpm` matched the
debounced Saleae value well, consistent with the GPIO input's own
Schmitt-trigger hysteresis already filtering this out at the hardware
level. Worth remembering for any future raw-capture Hall analysis: the
capture needs the same debounce step, don't count raw CSV rows
1:1 as edges.

**Promoted into a reusable module (2026-08-17): `analysis/hall_rpm.py`.**
`hall_edge_times()` (debounced Hall transitions from a digital.csv),
`rpm_from_edges()` (bin edges into an rpm trace), and the convenience
wrapper `hall_rpm_from_csv()` combining both. Re-derived from
`runs/2026-08-17_trigger_pin_test4/plot_hall_vs_lin_rpm.py`, which now
imports this module instead of duplicating the logic (confirmed
identical output before/after).

**Deliberately optional, not assumed present.** The Saleae is a
lab-only tool (root `CLAUDE.md`'s Data Flow section) — most runs won't
have a capture at all. `hall_rpm_from_csv()` returns `(None, None)`
if `csv_path` doesn't exist rather than raising, and `capture_available
(csv_path)` is exported for callers that want to check first. Any
future caller (e.g. the optimization loop's cost function) must treat
Hall-based rpm as opt-in per run, not a hard dependency — don't assume
every run has Saleae data.

**`find_sustained_high_edge()` / `has_sustained_high()` (added
2026-08-18)** — `find_sustained_high_edge()` returns the timestamp
where a given digital channel first reaches a stable HIGH for at least
some minimum duration (or `None`); `has_sustained_high()` is the
boolean wrapper. Distinguishes a genuine trigger-pin event (held for
seconds) from the ~100ns EMI-spike false triggers described above.
Built for `saleae-trigger-capture`'s retry loop (see
`saleae/CLAUDE.md`'s Trigger pin Open Point — `DigitalTriggerCaptureMode`'s
`pulse_high` trigger type turned out not to filter these in hardware,
so this classifies after the fact instead) and reused by
`plot-saleae-step-response` (new skill, also 2026-08-18) to
auto-align a Saleae capture's clock to a `capture_step_response.py`
log's clock — the trigger edge and the `speed` write that raised it are
the same LIN transaction, so it's a reliable shared t=0 regardless of
whether the capture was `timed` or `trigger` mode. Validated against
both a known-false capture (`saleae/exports/trigger_mode_test1/`,
correctly `False`) and a known-genuine one
(`saleae/exports/step_response_trigger_test4/`, correctly `True`).

**`plot-saleae-step-response` skill (added 2026-08-18) — confirmed
working end to end, including current.** Companion to
`/plot-step-response` (LIN-only): overlays LIN `rpm` against
`hall_rpm.py`'s Hall-edge `rpm`, auto-aligned via
`find_sustained_high_edge()`, for the case where a
`capture_step_response.py` CSV and a Saleae export already exist
independently (as opposed to `saleae-trigger-capture`, which produces
both itself and does this overlay internally as its own Analyze step).
Run against `runs/2026-08-18_trigger_capture/
capture_step_response_attempt2.csv` +
`saleae/exports/trigger_capture_2026-08-18_attempt2/`: auto-alignment
found `trigger_t≈0` (correct — that capture was `trigger` mode, so the
capture already starts at the trigger edge) and reproduced the same
overlay as the original one-off script, byte-for-byte equivalent
result. Same day, extended to also plot `current_val1`/`current_val2`
on a second axis (connected lines, not scatter — sparse in time
(~1/s, see `raspi/CLAUDE.md`'s `capture_step_response.py` entry) but
still a meaningful trend) — current only ever comes from the LIN side,
the Saleae capture itself has no current channel. Reference
implementation: `runs/2026-08-18_trigger_capture/plot_via_skill.py`.

## Cost Function (Grid/Gradient Search Metric)

**Decided 2026-08-21 (discussion only, not yet implemented): ISE
(integral/sum of squared error).** Subtract the setpoint step function
from the measured `rpm` trace, square each point, sum — low value means
good tracking, high value means poor tracking (overshoot, oscillation,
and slow settling all increase it). Standard step-response quality
metric; matches what the `hall_vs_lin_rpm.png` plots already visualize
by eye.

**Measurement source: LIN `rpm` for the grid search; Saleae Hall-edge
ground truth held in reserve for the gradient-search/validation phase,
not spent per grid point.** Reasoning from the 2026-08-21 discussion:
- **Scales to many unattended points.** A grid search calls
  `capture_step_response.py --p-delta/--i-delta` repeatedly; LIN-only
  needs no Saleae checklist/trigger-arm/false-trigger-retry/consent per
  point, sidestepping the already-flagged "one-consent-per-run doesn't
  scale to a full sweep" problem entirely for this phase (see the
  grid-search TODO item, root `CLAUDE.md`'s Goal).
- **Already validated as tracking Hall ground truth closely** across
  multiple prior runs (see Hall-Edge RPM Conversion above and
  `STM32/CLAUDE.md`'s `speed`≈`rpm` Open Points entry).
- **The known measurement artifacts apply roughly equally to every grid
  point** — same firmware measurement path (100ms free-running window
  not synced to the step event, 25rpm quantization; see
  `STM32/CLAUDE.md`'s RPM Measurement Resolution and Commutation &
  Control sections) for all of them — so they should mostly wash out of
  a *relative* ranking across candidates, even though they distort the
  absolute step-response shape (see the "dead time was mostly a ramp
  artifact" finding, 2026-08-20).
- **Reconsider for the gradient-search phase.** Fewer, more closely-
  spaced candidates around the grid search's best point means the same
  quantization/windowing noise that washes out across a coarse grid
  could obscure genuinely small differences there — Saleae ground truth
  may be worth bringing back in for that narrower phase, or at least
  for validating the final chosen point, not for scoring every point.

**Still open, not yet decided:** exact ISE window (whole capture vs.
just the step segment), how the 25rpm quantization/window-lag artifacts
get handled in the subtraction (if at all), and the concrete mechanism
for reintroducing Saleae in the gradient-search phase. Not implemented
yet — this is a design decision only so far.

## Open Points (analysis-specific)

- Whatever metric ends up including a dead-time/rise-time term must be
  computed only from ramp-disabled runs (`updateramp(false)`, current
  state as of 2026-08-20) — see `STM32/CLAUDE.md`'s Commutation &
  Control section: a ramp-enabled run's apparent dead time is mostly a
  ramp artifact, not the real motor/controller dynamics, confirmed by a
  direct before/after comparison on real hardware.

Fill this in here once fixed, not in the root `CLAUDE.md`.
