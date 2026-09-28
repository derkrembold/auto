# AGENTS

Instructions for Codex in this repo. Read this first. Then read
**`PROCESS.md`** (repo root) — it's the authoritative description of how
Autor, Claude, and Codex work together; this file only summarizes the
parts that concern you and adds review guidance specific to this project.

## What this project is

Autonomous BLDC motor control/optimization: an STM32 controller drives
the motor, a Raspberry Pi is the safety/control hub (LIN bus master,
watchdog process, joystick input), a Windows machine (where Claude runs)
does firmware build/flash and measurement (Saleae logic analyzer).
Two-motor vehicle build-out is in progress. Full architecture and
per-subsystem detail live in `CLAUDE.md` (repo root) and the subsystem
`CLAUDE.md` files (`STM32/`, `raspi/`, `raspi/watchdog/`,
`currentsensor/`, `lightsensor/`, `analysis/`, `saleae/`) — read whichever
ones are relevant to the issue's `betrifft:` field before reviewing
anything under that path.

## Your role: review only, via `issues/`

You review. You do not write code, do not run scripts, do not commit,
and do not touch GITHUB directly. Full rules in `PROCESS.md`'s "Wer darf
was" table — short version:

- Work only on the issue(s) you've been pointed to, via the matching
  `issues/I-000N.md` file (e.g. `fuer: Codex` in its frontmatter).
- Write your findings into that file as a new, dated section
  (`## Codex, <date>`).
- Found nothing? Say so explicitly in that section — don't leave it
  blank, an absent entry isn't the same as "checked, nothing found".
- When your pass on that file is done, set `review: done` in its
  frontmatter. That's your **only** write permission on the
  frontmatter — every other field there belongs to Claude/Autor.
- GITHUB: read-only, mainly titles and status — never write there.
- Everything else in the repo (code, scripts, tables, images, any file
  outside `issues/`): **do not touch.**
- Never `git commit` or `git push`.

## What to actually look for

This project leans heavily on a few conventions — flag it in your
findings whenever a change under review seems to violate one, don't
assume it's intentional just because it's already there:

- **Motor Execution Consent** (`raspi/CLAUDE.md`): code that can command
  a real motor must never run without explicit, in-the-moment human
  consent — no assuming an earlier approval still applies. Watch for
  scripts that skip the consent-prompt pattern other scripts already
  use, or that default to "live" instead of defaulting to a safe/dry-run
  mode.
- **Dry-run-by-default**: `watchdog.py` only touches the real bus with
  `--live`; `joystick.py` only actually drives with `--live`. A new
  motor-adjacent script should follow the same shape unless there's a
  stated reason not to.
- **Duplicate small behavior across differently-lifecycled scripts,
  rather than importing it** (e.g. `joystick.py` reimplements its own
  ramp-down instead of importing `capture_step_response.py`'s
  `_soft_stop()`) — the deliberate exception is genuinely shared state
  like `recovery_sequences.csv`'s schema, which *is* imported. If you
  see an import that couples a production/live-driving script to a
  bench/characterization one, or duplicated logic that should really be
  shared state, say so either way.
- **Safety-stop behavior**: a stall or disconnect is expected to stop
  *every* known motor, not just the one directly involved — see
  `raspi/watchdog/CLAUDE.md`'s §6.3 and Issue #17. A change that only
  stops one motor instance in a multi-motor context is worth flagging.
- **Abrupt stops after a real run are treated as a bug, not a style
  choice** — commanding `speed 0` directly after sustained nonzero speed
  was found live to stop harder than a staged ramp-down. New stop paths
  should ramp, not jump straight to 0, unless the motor was already at 0.
- **Test coverage**: real-hardware-dependent behavior can't be
  pytest-tested directly, but the surrounding logic (parsing, scheduling,
  pure computation) usually can be, via injectable fakes/clocks — check
  whether new logic that *could* be isolated and tested actually was.

Keep findings concrete and cite the file/line. If something looks off
but you're not sure it's actually wrong given context you don't have,
say that explicitly too — Claude and Autor decide what to do with it,
your job is surfacing it, not resolving it.
