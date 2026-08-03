---
name: deploy-raspi
description: Deploy raspi/ source and docs to the Raspberry Pi (motorpi.local). Use when the user asks to deploy, redeploy, or push changes to the Pi.
---

Run `raspi/deploy.sh` from the repo root. It copies `raspi/control/`'s
and `raspi/watchdog/`'s source files, plus both `CLAUDE.md` docs
(renaming the watchdog one to avoid colliding with the other — they're
both literally named `CLAUDE.md` in the repo, flattened into one
directory on the Pi), to `pi@motorpi.local:/home/pi/auto/`.

This only copies files — it never executes anything on the Pi. That
matches `raspi/CLAUDE.md`'s Motor Execution Consent rule: deploying is
fine on request, but running anything that can command the motor still
needs the user's explicit, in-the-moment consent, separately, every
time. Don't let "deploy" imply "and now run it."

`raspi/deploy.sh` already retries each `scp`/`ssh` call a few times on
its own — `motorpi.local` mDNS resolution has been transient/flaky in
practice, not usually a real connectivity problem. If it still fails
after those retries, that's worth actually looking into rather than
just running the script again.

If new files get added under `raspi/control/` or `raspi/watchdog/` that
need deploying, update `raspi/deploy.sh` itself (add them to the `scp`
list) rather than deploying them ad hoc outside the script — the whole
point is one place that knows the correct file list and the naming
gotcha.
