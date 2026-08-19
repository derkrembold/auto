#!/usr/bin/env python3
"""Standalone P/I step-response experiment runner -- like STM32/build.sh
or STM32/flash.sh, but for a full grid/gradient-search point: physical
checklist -> P/I delta input -> motor consent -> set P/I + arm the
Saleae trigger capture + run capture_step_response.py on the Pi
(retrying up to 3x if the trigger false-fires on EMI noise) ->
raspi/analyze_logs.py sanity check -> Hall-vs-LIN overlay plot. No
Claude needed at runtime -- this is the single-point runner a future
grid/gradient search loop would call repeatedly with different
--p-delta/--i-delta.

Wires together pieces already built and confirmed working on real
hardware -- see saleae/CLAUDE.md (Saleae trigger-mode capture, the
pulse_high-doesn't-work / false-trigger-classification story),
analysis/CLAUDE.md (Hall-edge rpm + has_sustained_high()),
raspi/CLAUDE.md (the `pi` command and capture_step_response.py's
--p-delta/--i-delta), and STM32/CLAUDE.md (the KP/KI mechanism itself)
for the full background on each piece -- this script does not repeat
that background, only the orchestration.

Usage:
    python3 run_experiment.py [p_delta i_delta]

p_delta/i_delta are prompted for interactively if not given as
positional args -- a human gets guided prompts, a future automated
search loop can call this non-interactively.

Range is deliberately NOT checked here beyond "is this a number" -- the
watchdog's own validate() (raspi/watchdog/watchdog.py's
PI_DELTA_MIN/MAX) is the single source of truth for the actual
-1.28..1.27 range, so it isn't duplicated client-side (two independent
range definitions would eventually drift apart). If the range is
wrong, capture_step_response.py's own --p-delta/--i-delta handling
rejects it and exits nonzero before the motor is touched at all, and
this script aborts everything else too (no Saleae capture is left
armed, no analysis, no plot) -- see _run_motor_capture() below.
"""
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "saleae_mcp"))
sys.path.insert(0, str(REPO_ROOT))

import server  # saleae_mcp/server.py
from analysis.hall_rpm import has_sustained_high, hall_rpm_from_csv

PI_HOST = "pi@motorpi.local"
DEVICE_ID = "DB59F8F22EA91DEA"  # real Logic Pro 16, see saleae/CLAUDE.md
CHANNELS = [0, 1, 2, 3]  # 0-2 = H1/H2/H3, 3 = trigger pin
SAMPLE_RATE = 10_000_000
MAX_ATTEMPTS = 3

CHECKLIST = """
Physische Vorbereitung (siehe saleae/CLAUDE.md's Physical Pre-Flight Checklist):
  2. Logic 2 GUI laeuft, Automation-Server aktiv
  3. Saleae Logic Pro 16 per USB angeschlossen
  4. Motor-Stromversorgung/Batterie an
  5. Verkabelung: Kanal 0-2 = H1/H2/H3, Kanal 3 = Trigger-Pin (J1/GPIO_PIN_12)
(1. STM32 laeuft und 6. Watchdog laeuft --live werden unten automatisch geprueft.)
"""


def _ssh_check(cmd):
    return subprocess.run(["ssh", PI_HOST, cmd], capture_output=True, text=True)


def _check_stm32_and_watchdog():
    result = _ssh_check("pgrep -af watchdog.py; echo '---'; tail -3 /home/pi/auto/watchdog.log")
    print(result.stdout)
    if "watchdog.py --live" not in result.stdout:
        sys.exit("Watchdog läuft nicht --live auf dem Pi. Abbruch.")
    if "ret=0" not in result.stdout:
        sys.exit("STM32 antwortet nicht (kein 'ret=0' in den letzten Log-Zeilen). Abbruch.")


def _get_pi_deltas():
    if len(sys.argv) == 3:
        try:
            return float(sys.argv[1]), float(sys.argv[2])
        except ValueError:
            sys.exit("p_delta/i_delta müssen Zahlen sein.")
    while True:
        try:
            p_delta = float(input("P delta: ").strip())
            i_delta = float(input("I delta: ").strip())
            return p_delta, i_delta
        except ValueError:
            print("Bitte eine Zahl eingeben.")


def _confirm(prompt):
    return input(f"{prompt} [y/N]: ").strip().lower() == "y"


def _run_motor_capture(p_delta, i_delta, csv_path):
    # stdout/stderr captured separately (not merged via 2>&1) so ssh's
    # own banner text never ends up mixed into the CSV -- a real
    # gotcha hit earlier this project when redirecting a plain `> file
    # 2>&1`.
    cmd = (f"cd /home/pi/auto && python3 capture_step_response.py "
           f"--p-delta {p_delta} --i-delta {i_delta}")
    result = subprocess.run(["ssh", PI_HOST, cmd], capture_output=True, text=True)
    csv_path.write_text(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        return False
    return True


def _arm_trigger_capture():
    res = server.start_capture(
        device_id=DEVICE_ID, digital_channels=CHANNELS,
        digital_sample_rate=SAMPLE_RATE, capture_mode="trigger",
        trigger_channel_index=3, trigger_type="rising",
        after_trigger_seconds=10,
    )
    return res["capture_id"]


def _finish_capture(capture_id, export_name):
    # wait_for_capture_or_timeout(), not bare wait_for_capture() -- an
    # abandoned wait leaves Logic 2 stuck "recording" until someone
    # clicks Stop in the GUI by hand, hit live twice building the
    # saleae-trigger-capture skill this mirrors. See that skill's
    # SKILL.md and saleae/CLAUDE.md's Trigger pin Open Point.
    result = server.wait_for_capture_or_timeout(capture_id, timeout_seconds=20)
    export_res = server.export_capture(capture_id, export_name, digital_channels=CHANNELS)
    server.save_capture(capture_id, export_name)
    server.close_capture(capture_id)
    if result["status"] != "completed":
        return None
    digital_csv = str(Path(export_res["export_dir"]) / "digital.csv")
    if not has_sustained_high(digital_csv):
        return None  # false trigger -- EMI spike, not a real motor run
    return digital_csv


def _abort_pending_capture(capture_id):
    # Cleanup for the "pi command rejected" abort path: the trigger
    # capture is already armed on the Saleae side by the time we find
    # that out, and would otherwise be left orphaned -- same
    # stuck-recording risk as an abandoned wait, see _finish_capture().
    try:
        server.stop_capture(capture_id)
        server.close_capture(capture_id)
    except Exception:
        pass


def _make_plot(motor_csv, digital_csv, out_path, p_delta, i_delta):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from analysis.hall_rpm import find_sustained_high_edge

    trigger_t = find_sustained_high_edge(digital_csv)

    lin_t, lin_rpm = [], []
    cur_t, cur_val1, cur_val2 = [], [], []
    for line in motor_csv.read_text().splitlines():
        parts = line.strip().split(",")
        if len(parts) != 4 or not parts[0].isdigit():
            continue
        elapsed_ms, rpm, val1, val2 = parts
        t = int(elapsed_ms) / 1000
        lin_t.append(t)
        lin_rpm.append(int(rpm))
        if val1 and val2:
            cur_t.append(t)
            cur_val1.append(float(val1))
            cur_val2.append(float(val2))

    hall_t, hall_rpm = hall_rpm_from_csv(digital_csv, bin_s=0.1, t0=0.0)
    hall_t = [t - trigger_t for t in hall_t]

    fig, ax1 = plt.subplots(figsize=(11, 6))
    l1, = ax1.step(lin_t, lin_rpm, where="mid", color="tab:blue", linewidth=1.5,
                    label="LIN st2mot `rpm`")
    l2, = ax1.plot(hall_t, hall_rpm, color="tab:orange", linewidth=1.2,
                    marker=".", markersize=3, label="Saleae Hall-edge rpm (ground truth)")
    ax1.set_xlabel("time since trigger [s]")
    ax1.set_ylabel("rpm")

    ax2 = ax1.twinx()
    l3, = ax2.plot(cur_t, cur_val1, color="tab:red", marker="s", markersize=5,
                    linewidth=1.2, label="current_val1 [A]")
    l4, = ax2.plot(cur_t, cur_val2, color="tab:purple", marker="^", markersize=5,
                    linewidth=1.2, label="current_val2 [A]")
    ax2.set_ylabel("current [A]")

    ax1.set_title(f"run_experiment.py: P delta={p_delta}, I delta={i_delta}")
    ax1.legend(handles=[l1, l2, l3, l4], loc="lower right", fontsize=9)
    ax1.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)


def main():
    print(CHECKLIST)
    _check_stm32_and_watchdog()
    if not _confirm("Checkliste erledigt, alles bereit?"):
        sys.exit("Abgebrochen.")

    p_delta, i_delta = _get_pi_deltas()

    if not _confirm(f"Motor jetzt starten (P delta={p_delta}, I delta={i_delta})?"):
        sys.exit("Abgebrochen.")

    timestamp = time.strftime("%Y-%m-%d_%H%M%S")
    run_dir = REPO_ROOT / "runs" / f"{timestamp}_experiment"
    run_dir.mkdir(parents=True, exist_ok=True)
    motor_csv = run_dir / "capture_step_response.csv"

    digital_csv = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"Versuch {attempt}/{MAX_ATTEMPTS} ...")
        export_name = f"experiment_{timestamp}_attempt{attempt}"
        capture_id = _arm_trigger_capture()

        if not _run_motor_capture(p_delta, i_delta, motor_csv):
            _abort_pending_capture(capture_id)
            sys.exit("Motorlauf abgebrochen (siehe Fehlermeldung oben) — nichts weiter unternommen.")

        digital_csv = _finish_capture(capture_id, export_name)
        if digital_csv:
            print("Echter Trigger erkannt.")
            break
        print("Fehlalarm (Störimpuls) oder Timeout — versuche nochmal.")
    else:
        sys.exit(f"{MAX_ATTEMPTS} Versuche fehlgeschlagen, kein echter Trigger — Abbruch.")

    fetched_logs = []
    for f in ("watchdog.log", "capture_step_response.log"):
        # motorpi.local mDNS resolution is known to fail intermittently
        # across repeated calls in one script -- retry individually
        # rather than treating one failed fetch as "file doesn't exist"
        # (see the analyze-logs skill's own note on this exact gotcha).
        # A silently-skipped failure here previously crashed
        # analyze_logs.py downstream with a confusing FileNotFoundError
        # instead of a clear message -- hit live 2026-08-19.
        for attempt in range(3):
            result = subprocess.run(["scp", f"{PI_HOST}:/home/pi/auto/{f}", str(run_dir)],
                                     capture_output=True, text=True)
            if result.returncode == 0:
                fetched_logs.append(str(run_dir / f))
                break
            time.sleep(1)
        else:
            print(f"WARNUNG: Fetch von {f} fehlgeschlagen (3 Versuche): {result.stderr.strip()}")

    if fetched_logs:
        print("\n--- analyze_logs.py ---")
        analyze = subprocess.run(
            [sys.executable, str(REPO_ROOT / "raspi" / "analyze_logs.py"), *fetched_logs]
        )
        if analyze.returncode != 0:
            print("WARNUNG: analyze_logs.py hat Auffälligkeiten gefunden, siehe oben.")
    else:
        print("WARNUNG: keine Logs abholbar, analyze_logs.py übersprungen.")

    plot_path = run_dir / "hall_vs_lin_rpm.png"
    _make_plot(motor_csv, digital_csv, plot_path, p_delta, i_delta)
    print(f"\nFertig. Ergebnisse in {run_dir}")
    print(f"Plot: {plot_path}")


if __name__ == "__main__":
    try:
        main()
    finally:
        # Always closes even on sys.exit()/an uncaught exception mid-run
        # -- see close_manager()'s own docstring for why this is needed
        # at all (an unclosed Manager connection otherwise hangs the
        # process on exit until Ctrl-C).
        server.close_manager()
