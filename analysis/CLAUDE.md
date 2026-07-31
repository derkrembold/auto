# analysis — Context for Claude Code

This folder turns raw Saleae captures into speed data and control-quality
metrics for the optimization loop described in the root `CLAUDE.md`.

## Purpose

- Compute instantaneous motor speed from Saleae Hall-edge captures
  (`saleae/exports/`) — time between edge transitions on the 3 Hall
  channels.
- Derive control-quality metrics/cost from a run's speed trace, used to
  produce the next parameter set in the optimization loop.

## Open Points (analysis-specific)

- Cost function/metric weighting for the optimization loop — not yet
  defined.

Fill this in here once fixed, not in the root `CLAUDE.md`.
