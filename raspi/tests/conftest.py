import sys
from pathlib import Path

# raspi/control/ and raspi/watchdog/ are separate source folders (deploy
# flattens them into one directory on the Pi, but the repo doesn't) — add
# both to sys.path so tests can import their modules directly. raspi/
# itself is added too, for top-level modules like analyze_logs.py that
# aren't deployed to the Pi at all (local analysis tool only).
RASPI_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RASPI_ROOT))
sys.path.insert(0, str(RASPI_ROOT / "control"))
sys.path.insert(0, str(RASPI_ROOT / "watchdog"))
