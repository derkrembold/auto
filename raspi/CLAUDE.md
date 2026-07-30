# raspi — Context for Claude Code

This folder contains the code that runs on the Raspberry Pi. The Pi itself
is a pure execution node with no git checkout of its own — development and
versioning happen here in the repo, deployment happens via SCP/SSH.

## Access

- **Hostname:** `motorpi.local` (mDNS — usable on the local network,
  independent of a changing IP)
- **User:** `pi`
- **Auth:** SSH key (ed25519), passwordless. Key lives at
  `C:\Users\rembo\.ssh\id_ed25519` — **not** inside this repo.
- There is a second Raspberry Pi on the same network — do not confuse
  them. Only `motorpi.local` is the motor controller Pi.

Connection test:
```
ssh pi@motorpi.local
```
Should log in directly without a password prompt.

## Deployment Pattern

Code from `raspi/control/` resp. `raspi/watchdog/` is pushed to the Pi via
`scp`/`rsync`, executed there, and results/logs are read back. No manual
editing of code directly on the Pi — always make changes here in the repo,
then redeploy, so the repo and the actual state on the Pi don't drift
apart.

## Structure

- `control/` — LIN master code (Start/Stop/Speed commands), already
  implemented.
- `watchdog/` — Independent safety barrier. Runs as its own process,
  separate from the rest. Must be able to stop the motor on its own,
  regardless of whether Claude Code / the optimization loop is still
  responding or not. Limits (max speed, timeout without heartbeat) belong
  here in the code, not in prompts.

## Security Note

Never place or commit private keys, passwords, or `known_hosts` contents
in this folder — see `.gitignore` at the repo root.
