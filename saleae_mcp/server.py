"""MCP server wrapping the Saleae Logic 2 Automation API (`logic2-automation`,
imported as `saleae.automation`).

Lives in its own top-level `saleae_mcp/` directory, not inside `saleae/` --
the installed `saleae` package and this repo's own `saleae/` folder are both
namespace packages with the same name, so Python merges them when the repo
root is on sys.path. Keeping this file out of `saleae/` avoids any ambiguity
about which "saleae" a given import resolves to.

Connects to an already-running Logic 2 instance with the Automation API
enabled (Preferences, scroll to bottom, or launch with `--automation
--automationPort 10430`) -- headful by design for now, so captures can be
watched live in the GUI. See saleae/CLAUDE.md for the channel/trigger
layout this project actually uses (3 Hall channels + 1 trigger channel).

Run directly for local testing: `python server.py`
Registered with Claude Code as an MCP server named "saleae".
"""
import threading
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from saleae import automation

mcp = MCPServer("saleae")

DEFAULT_PORT = 10430
EXPORT_DIR = Path(__file__).resolve().parent.parent / "saleae" / "exports"

_manager: automation.Manager | None = None
_captures: dict[int, automation.Capture] = {}

_TRIGGER_TYPES = {
    "rising": automation.DigitalTriggerType.RISING,
    "falling": automation.DigitalTriggerType.FALLING,
    "pulse_high": automation.DigitalTriggerType.PULSE_HIGH,
    "pulse_low": automation.DigitalTriggerType.PULSE_LOW,
}


def _get_manager() -> automation.Manager:
    # Connects lazily, once, on first tool call -- not at import time, so
    # importing this module (e.g. for tests) never touches the network.
    global _manager
    if _manager is None:
        _manager = automation.Manager.connect(port=DEFAULT_PORT, connect_timeout_seconds=5)
    return _manager


def close_manager() -> None:
    # automation.Manager.connect() opens a connection (gRPC under the
    # hood) that keeps the Python process alive after main() returns if
    # never closed -- a standalone script (run_experiment.py) that
    # never calls this hangs on exit until Ctrl-C, hit live 2026-08-19.
    # Plain function, not an @mcp.tool() -- Claude's own MCP session
    # lifecycle is managed by the MCP protocol layer, not by calling
    # this; it's for standalone-script callers only.
    global _manager
    if _manager is not None:
        _manager.close()
        _manager = None


def _require_capture(capture_id: int) -> automation.Capture:
    if capture_id not in _captures:
        raise ValueError(
            f"Unknown capture_id {capture_id} -- not started via start_capture(), "
            f"or already closed via close_capture()."
        )
    return _captures[capture_id]


@mcp.tool()
def list_devices(include_simulation: bool = False) -> list[dict]:
    """List Saleae devices visible to the connected Logic 2 instance."""
    manager = _get_manager()
    devices = manager.get_devices(include_simulation_devices=include_simulation)
    return [
        {
            "device_id": d.device_id,
            "device_type": d.device_type.name,
            "is_simulation": d.is_simulation,
        }
        for d in devices
    ]


@mcp.tool()
def start_capture(
    device_id: str,
    digital_channels: list[int],
    digital_sample_rate: int,
    capture_mode: str = "manual",
    duration_seconds: float | None = None,
    trigger_channel_index: int | None = None,
    trigger_type: str = "rising",
    after_trigger_seconds: float | None = None,
    min_pulse_width_seconds: float | None = None,
    max_pulse_width_seconds: float | None = None,
    analog_channels: list[int] | None = None,
    analog_sample_rate: int | None = None,
    buffer_size_megabytes: int | None = None,
) -> dict:
    """Start a new capture. Returns a capture_id for use with the other
    capture tools (wait_for_capture, stop_capture, export_capture,
    save_capture, close_capture).

    capture_mode:
      - "manual": runs until stop_capture() is called.
      - "timed": runs for duration_seconds, then stops on its own.
      - "trigger": arms on a digital edge/pulse on trigger_channel_index
        (trigger_type: rising/falling/pulse_high/pulse_low), captures
        after_trigger_seconds of data after it fires, then stops on its
        own. Matches this project's hardware trigger pin (see root
        CLAUDE.md's Data Flow section) -- no software sync needed.

    pulse_high/pulse_low + min_pulse_width_seconds/max_pulse_width_seconds
    were added 2026-08-18 to filter this project's trigger pin's ~100ns
    EMI spikes (see analysis/CLAUDE.md's debounce finding) out of a
    rising-edge trigger -- but confirmed broken the same day, against
    both the real Logic Pro 16 and the simulation device: pulse_high
    never fires at all (tested with and without a width filter, up to
    15s waited). Root cause not in this project's code -- looks like a
    logic2-automation library issue. Use trigger_type="rising" instead;
    see saleae/CLAUDE.md's Trigger pin Open Point for the false-trigger
    risk that leaves open (and analysis/hall_rpm.py's
    has_sustained_high() for classifying a resulting capture as
    real-vs-noise after the fact) and wait_for_capture_or_timeout()
    below for avoiding an indefinite hang if a trigger never fires.
    """
    manager = _get_manager()

    device_configuration = automation.LogicDeviceConfiguration(
        enabled_digital_channels=digital_channels,
        enabled_analog_channels=analog_channels or [],
        digital_sample_rate=digital_sample_rate,
        analog_sample_rate=analog_sample_rate,
    )

    if capture_mode == "manual":
        mode = automation.ManualCaptureMode()
    elif capture_mode == "timed":
        if duration_seconds is None:
            raise ValueError("duration_seconds is required for capture_mode='timed'")
        mode = automation.TimedCaptureMode(duration_seconds=duration_seconds)
    elif capture_mode == "trigger":
        if trigger_channel_index is None:
            raise ValueError("trigger_channel_index is required for capture_mode='trigger'")
        if trigger_type not in _TRIGGER_TYPES:
            raise ValueError(f"trigger_type must be one of {sorted(_TRIGGER_TYPES)}")
        mode = automation.DigitalTriggerCaptureMode(
            trigger_type=_TRIGGER_TYPES[trigger_type],
            trigger_channel_index=trigger_channel_index,
            after_trigger_seconds=after_trigger_seconds,
            min_pulse_width_seconds=min_pulse_width_seconds,
            max_pulse_width_seconds=max_pulse_width_seconds,
        )
    else:
        raise ValueError("capture_mode must be 'manual', 'timed', or 'trigger'")

    capture_configuration = automation.CaptureConfiguration(
        capture_mode=mode,
        buffer_size_megabytes=buffer_size_megabytes,
    )

    capture = manager.start_capture(
        device_id=device_id,
        device_configuration=device_configuration,
        capture_configuration=capture_configuration,
    )
    _captures[capture.capture_id] = capture
    return {"capture_id": capture.capture_id, "capture_mode": capture_mode}


@mcp.tool()
def wait_for_capture(capture_id: int) -> dict:
    """Block until a 'timed' or 'trigger' mode capture finishes on its own.
    Do not call this for 'manual' mode -- use stop_capture() instead, it
    never finishes on its own."""
    capture = _require_capture(capture_id)
    capture.wait()
    return {"capture_id": capture_id, "status": "completed"}


@mcp.tool()
def wait_for_capture_or_timeout(capture_id: int, timeout_seconds: float) -> dict:
    """Like wait_for_capture(), but never blocks past timeout_seconds --
    calls stop_capture() internally if the trigger/timed condition
    hasn't completed by then. Prefer this over wait_for_capture() for
    'trigger' mode: an abandoned wait_for_capture() call (killed
    process, tool timeout) leaves the capture running on the Logic 2
    side with nothing left to ever call stop_capture()/close_capture()
    on it -- Logic 2 gets stuck "recording" and every subsequent
    start_capture() fails with InternalServerError until someone clicks
    Stop by hand in the GUI (hit live 2026-08-18, twice, waiting on a
    trigger_type='pulse_high' capture that turned out to never fire --
    see start_capture()'s docstring)."""
    capture = _require_capture(capture_id)
    done = threading.Event()

    def waiter():
        capture.wait()
        done.set()

    threading.Thread(target=waiter, daemon=True).start()
    if done.wait(timeout=timeout_seconds):
        return {"capture_id": capture_id, "status": "completed"}
    capture.stop()
    return {"capture_id": capture_id, "status": "timed_out"}


@mcp.tool()
def stop_capture(capture_id: int) -> dict:
    """Manually stop a capture. Required to end 'manual' mode captures;
    also works to end a 'timed'/'trigger' capture early."""
    capture = _require_capture(capture_id)
    capture.stop()
    return {"capture_id": capture_id, "status": "stopped"}


@mcp.tool()
def export_capture(
    capture_id: int,
    export_name: str,
    digital_channels: list[int] | None = None,
    analog_channels: list[int] | None = None,
    analog_downsample_ratio: int = 1,
) -> dict:
    """Export a completed (stopped/finished) capture's raw data as CSV.
    Writes into saleae/exports/<export_name>/ (one CSV per channel --
    the underlying API exports into a directory, not a single file)."""
    capture = _require_capture(capture_id)
    target_dir = EXPORT_DIR / export_name
    target_dir.mkdir(parents=True, exist_ok=True)
    capture.export_raw_data_csv(
        str(target_dir),
        digital_channels=digital_channels,
        analog_channels=analog_channels,
        analog_downsample_ratio=analog_downsample_ratio,
    )
    return {"capture_id": capture_id, "export_dir": str(target_dir)}


@mcp.tool()
def save_capture(capture_id: int, filename: str) -> dict:
    """Save a completed capture as a native .sal file (full-fidelity,
    reopenable in the Logic 2 GUI) into saleae/exports/."""
    capture = _require_capture(capture_id)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    if not filename.endswith(".sal"):
        filename += ".sal"
    filepath = EXPORT_DIR / filename
    capture.save_capture(str(filepath))
    return {"capture_id": capture_id, "filepath": str(filepath)}


@mcp.tool()
def close_capture(capture_id: int) -> dict:
    """Release a capture's resources in Logic 2. Call after exporting/
    saving -- a capture left open holds memory in Logic 2 until closed."""
    capture = _require_capture(capture_id)
    capture.close()
    del _captures[capture_id]
    return {"capture_id": capture_id, "status": "closed"}


if __name__ == "__main__":
    mcp.run()
