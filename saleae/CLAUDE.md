# saleae — Context for Claude Code

This folder holds the Saleae Logic Pro 16 capture configuration and
exported captures for the BLDC motor speed measurement setup described in
the root `CLAUDE.md`.

## Purpose

The Saleae records the motor's 3 Hall sensor channels plus a trigger
channel (4 channels total), non-invasively — tapped off signals the
firmware already needs for commutation, no firmware changes required.
Speed is computed in software from the time between Hall edge transitions
(see `analysis/`). This replaces LIN-based measurement readback entirely —
the Raspi/LIN side is control-only now.

## Structure

- `capture_config/` — channel mapping, trigger setup, sample rate for the
  Saleae capture.
- `exports/` — raw capture exports, one per test run, paired with that
  run's parameter set/metrics under `runs/`.

## Open Points (Saleae-specific)

- Exact pin mapping — which Hall channel maps to which Saleae input, and
  the trigger pin.
- Sample rate for the Hall channels — needs to resolve commutation edge
  timing at max RPM without producing unmanageable capture sizes.

Fill these in here once fixed, not in the root `CLAUDE.md`.
