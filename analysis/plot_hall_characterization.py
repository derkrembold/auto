#!/usr/bin/env python3
"""Plots raspi/control/characterize_hall_positions.py's output: how many
escalation attempts ("fires") a pulse needed to break the rotor free of
its Hall position, per iteration of one automatic run -- see root
CLAUDE.md's LIN Protocol section and analysis/grid_search_log.md's
2026-08-28 Dead Zone/cogging-torque discussion for the background this
supports.

x-axis: a cumulative LOGICAL Hall-state position, not the raw
`position_index` -- a pulse can skip more than one electrical state in
a single measured transition (see the grid_search_log.md entry on
multi-state jumps), so two runs whose transitions skip a different
number of states would otherwise drift out of alignment against a
plain 1..N index. Instead, each row's step size (how many electrical
states it actually advanced -- direction-aware: `(new-ref) % 6` for cw,
`(ref-new) % 6` for ccw) is accumulated, so a given Hall state lands at
the same x position across every file, and skipped-over states still
get an x-axis tick/label (computed, not measured -- "aufgefuellt", per
the user's own phrasing 2026-08-28) even though no data point exists
there. Data points are drawn as markers only, connected by a thin
dashed line -- deliberately NOT a bold step line through the skipped
positions, since we have no measurement for what "attempts" would have
been at a state that got skipped over, only for the ones actually
pulse-tested.

y-axis: `attempts` (escalation steps needed) at each actually-measured
position.

Multiple CSVs (e.g. repeated runs) can be overlaid on one chart for a
direct reproducibility comparison, one line per file -- most useful
when every file starts from the same controlled Hall position (see
grid_search_log.md's "cut" to controlled starting position,
2026-08-28), otherwise each file's own x=0 is just wherever it
happened to start.

Usage:
    python3 analysis/plot_hall_characterization.py <csv> [<csv> ...] [--out path.png]
"""
import argparse
import csv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _read_rows(csv_path):
    with open(csv_path, newline="") as f:
        return list(csv.DictReader(f))


def _step_size(hal_ref_state, hal_new_state, direction):
    # Electrical states cycle 0..5; direction decides which way "next"
    # means -- mirrors main.c's own driveStep() CW/CCW ordering.
    if hal_new_state == "" or hal_new_state is None or hal_new_state == hal_ref_state:
        return 0  # no permanent transition (ceiling hit) -- stayed put
    ref, new = int(hal_ref_state), int(hal_new_state)
    return (new - ref) % 6 if direction == 1 else (ref - new) % 6


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_paths", nargs="+")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(15, 6))

    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    max_x = 0
    label_start_state = None
    label_direction = 1

    for i, csv_path in enumerate(args.csv_paths):
        rows = _read_rows(csv_path)
        if not rows:
            continue
        direction = int(rows[0]["direction"])
        if label_start_state is None:
            label_start_state = int(rows[0]["hal_ref_state"])
            label_direction = direction

        xs, ys, stuck_xs, stuck_ys = [], [], [], []
        cum_x = 0
        for r in rows:
            xs.append(cum_x)
            ys.append(int(r["attempts"]))
            if not r["threshold_pulse"]:
                stuck_xs.append(cum_x)
                stuck_ys.append(int(r["attempts"]))
            cum_x += _step_size(r["hal_ref_state"], r["hal_new_state"], direction)
        max_x = max(max_x, cum_x)

        name = Path(csv_path).stem
        if len(args.csv_paths) > 8:
            # With many files (e.g. a whole q0 batch), most traces are
            # near-identical -- a distinct color+legend entry per file
            # is unreadable and the individual filename isn't
            # meaningful anyway. Draw every line the same translucent
            # color instead: overlapping (= reproducible) segments
            # visually reinforce into a darker/opaque line, rare
            # divergent paths stay faint. No per-file legend in this
            # mode, just a summary label.
            ax.plot(xs, ys, marker="o", markersize=5, linestyle="-", linewidth=1.2,
                    color="tab:blue", alpha=0.25, zorder=3,
                    label=f"{len(args.csv_paths)} Läufe (übereinandergelegt)" if i == 0 else None)
            if stuck_xs:
                ax.scatter(stuck_xs, stuck_ys, color="tab:red", marker="x", s=140,
                           alpha=0.6, zorder=5)
        else:
            color = colors[i % len(colors)]
            ax.plot(xs, ys, marker="o", markersize=4, linestyle="--", linewidth=0.8,
                    color=color, label=name)
            if stuck_xs:
                ax.scatter(stuck_xs, stuck_ys, color=color, marker="x", s=120, zorder=5)

    ax.set_xlabel(f"kumulierte logische Hall-Position (aufgefuellt bei übersprungenen "
                  f"Zuständen -- state-Beschriftung ausgehend von Datei 1's Start "
                  f"state={label_start_state}, Richtung {'cw' if label_direction == 1 else 'ccw'})")
    ax.set_ylabel("Anzahl Eskalationsversuche (\"Fires\") bis zum Durchbruch")
    ax.set_title("characterize_hall_positions.py: Eskalationsversuche pro logischer Hall-Position")

    tick_positions = list(range(0, max_x + 1))
    # Inverse of _step_size()'s own convention: cw advances state = ref + x,
    # ccw advances state = ref - x, for x logical steps from the start.
    tick_labels = [
        f"{x}\n({(label_start_state + x) % 6 if label_direction == 1 else (label_start_state - x) % 6})"
        for x in tick_positions
    ]
    # Thin out labels if there are many, to avoid an unreadable axis.
    label_every = max(1, len(tick_positions) // 40)
    ax.set_xticks(tick_positions)
    ax.set_xticklabels([lbl if idx % label_every == 0 else "" for idx, lbl in enumerate(tick_labels)],
                        fontsize=7)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right", fontsize=9)
    fig.tight_layout()

    out_path = args.out or (Path(args.csv_paths[0]).parent / "hall_characterization_attempts.png")
    fig.savefig(out_path, dpi=150)
    print(f"Chart: {out_path}")


if __name__ == "__main__":
    main()
