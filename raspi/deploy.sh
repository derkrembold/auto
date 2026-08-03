#!/bin/bash
# Deploys raspi/ source + docs to the Pi's /home/pi/auto/ (flat directory
# — see raspi/CLAUDE.md's Deployment Pattern section for why). Copy only,
# nothing gets executed on the Pi by this script — see raspi/CLAUDE.md's
# Motor Execution Consent rule for why that matters.
set -euo pipefail

HOST="pi@motorpi.local"
TARGET="/home/pi/auto/"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# motorpi.local's mDNS resolution has been observed to fail
# intermittently — especially across repeated scp/ssh calls within one
# script run, even when a lone ssh call right before/after succeeds.
# Retry a few times before giving up, rather than making every deploy a
# manual retry loop.
run_with_retry() {
    local attempt
    for attempt in 1 2 3; do
        if "$@"; then
            return 0
        fi
        echo "  (attempt $attempt failed, retrying...)" >&2
        sleep 1
    done
    echo "  giving up after 3 attempts: $*" >&2
    return 1
}

echo "Deploying to $HOST:$TARGET (copy only, nothing executed)"

run_with_retry scp \
  "$REPO_ROOT/raspi/control/motorcontrol.py" \
  "$REPO_ROOT/raspi/control/linaddresses.py" \
  "$REPO_ROOT/raspi/watchdog/watchdog.py" \
  "$REPO_ROOT/raspi/watchdog/linbus.py" \
  "$HOST:$TARGET"

# Docs — raspi/CLAUDE.md and raspi/watchdog/CLAUDE.md are both literally
# named CLAUDE.md in the repo. They'd silently overwrite each other in
# this flat deploy directory (this happened once, by hand) — the
# watchdog one gets renamed on the way out to avoid that.
run_with_retry scp "$REPO_ROOT/raspi/CLAUDE.md" "$HOST:${TARGET}CLAUDE.md"
run_with_retry scp "$REPO_ROOT/raspi/watchdog/CLAUDE.md" "$HOST:${TARGET}watchdog-CLAUDE.md"

echo "Done. Current state of $TARGET:"
run_with_retry ssh "$HOST" "ls -la $TARGET"
