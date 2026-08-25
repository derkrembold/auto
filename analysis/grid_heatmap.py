#!/usr/bin/env python3
"""Merge multiple run_grid.py/run_grid_row.py output directories into
combined ISE/MSSD heatmaps over the (P delta, I delta) plane.

Read-only, no motor interaction, no consent needed -- purely reads each
given directory's grid_results.csv (same column schema for both
run_grid.py's 3x3 grids and run_grid_row.py's 9-point rows, see
CLAUDE.md's Grid Search section) and combines them.

If the same (P delta, I delta) coordinate appears in more than one
input directory (e.g. a repeated row, or a row and a grid overlapping
at their shared center point), the values are averaged, not just the
last one kept silently -- the observation count per cell is tracked
and printed, since the whole point of tracking repeatability so far in
this project (see analysis/grid_search_log.md) is to never silently
hide how many measurements a number is based on.

Usage:
    python3 analysis/grid_heatmap.py <run_dir1> [<run_dir2> ...]

Produces, in a new runs/<timestamp>_heatmap/ directory:
    heatmap_ise.png
    heatmap_mssd_2s.png
    heatmap_mssd_full.png
    heatmap_data.csv   (the merged/averaged dataset, for reuse)

(0, 0) is marked as the current firmware default (KPDEFAULT/KIDEFAULT),
not as a claim about being the best point -- see CLAUDE.md's Candidate
Selection Philosophy section for why that distinction matters. The
single lowest-ISE point found is marked separately.
"""
import csv
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

METRICS = ("ise", "mssd_2s", "mssd_full")


def _load_results(run_dirs):
    observations = defaultdict(list)
    for run_dir in run_dirs:
        csv_path = run_dir / "grid_results.csv"
        if not csv_path.exists():
            print(f"WARNUNG: keine grid_results.csv in {run_dir}, übersprungen.")
            continue
        with open(csv_path, newline="") as f:
            for row in csv.DictReader(f):
                key = (round(float(row["p_delta"]), 3), round(float(row["i_delta"]), 3))
                try:
                    observations[key].append({m: float(row[m]) for m in METRICS})
                except KeyError:
                    sys.exit(f"{csv_path} fehlt eine der Spalten {METRICS} -- "
                             f"alte tv_2s/tv_full-Datei? Bitte mit aktuellem "
                             f"run_grid.py/run_grid_row.py neu erzeugen.")
    return observations


def _average(observations):
    averaged = {}
    for key, obs_list in observations.items():
        n = len(obs_list)
        averaged[key] = {m: sum(o[m] for o in obs_list) / n for m in METRICS}
        averaged[key]["n"] = n
    return averaged


def _write_heatmap_csv(averaged, out_path):
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["p_delta", "i_delta", "ise", "mssd_2s", "mssd_full", "n_observations"])
        for (p, i), r in sorted(averaged.items()):
            writer.writerow([p, i, r["ise"], r["mssd_2s"], r["mssd_full"], r["n"]])


def _make_heatmap(averaged, metric, title, out_path, best_key):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    p_values = sorted({p for p, _ in averaged})
    i_values = sorted({i for _, i in averaged})

    grid = np.full((len(i_values), len(p_values)), np.nan)
    counts = np.zeros((len(i_values), len(p_values)), dtype=int)
    for (p, i), r in averaged.items():
        row = i_values.index(i)
        col = p_values.index(p)
        grid[row, col] = r[metric]
        counts[row, col] = r["n"]

    fig, ax = plt.subplots(figsize=(max(6, len(p_values) * 1.15), max(5, len(i_values) * 1.0)))
    masked = np.ma.masked_invalid(grid)
    im = ax.imshow(masked, cmap="viridis", origin="lower", aspect="auto")
    ax.set_xticks(range(len(p_values)))
    ax.set_xticklabels([f"{p:+.2f}" for p in p_values], rotation=45, ha="right")
    ax.set_yticks(range(len(i_values)))
    ax.set_yticklabels([f"{i:+.2f}" for i in i_values])
    ax.set_xlabel("P delta")
    ax.set_ylabel("I delta")
    ax.set_title(title)
    fig.colorbar(im, ax=ax, label=metric)

    for row in range(len(i_values)):
        for col in range(len(p_values)):
            val = grid[row, col]
            if np.isnan(val):
                continue
            label = f"{val:.0f}"
            if counts[row, col] > 1:
                label += f"\n(n={counts[row, col]})"
            ax.text(col, row, label, ha="center", va="center", color="white", fontsize=7)

    if 0.0 in p_values and 0.0 in i_values:
        ax.plot(p_values.index(0.0), i_values.index(0.0), marker="o", markersize=16,
                 markerfacecolor="none", markeredgecolor="red", markeredgewidth=2,
                 label="aktueller Regler-Istwert (0,0)")

    if best_key in averaged:
        bp, bi = best_key
        if bp in p_values and bi in i_values:
            ax.plot(p_values.index(bp), i_values.index(bi), marker="*", markersize=18,
                     markerfacecolor="none", markeredgecolor="orange", markeredgewidth=2,
                     label=f"bester ISE-Punkt ({bp:+.2f}, {bi:+.2f})")

    ax.legend(loc="upper left", bbox_to_anchor=(1.15, 1.0), fontsize=8)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 analysis/grid_heatmap.py <run_dir1> [<run_dir2> ...]")

    run_dirs = []
    for arg in sys.argv[1:]:
        p = Path(arg)
        if not p.is_dir():
            print(f"WARNUNG: {p} ist kein Verzeichnis, übersprungen.")
            continue
        run_dirs.append(p)
    if not run_dirs:
        sys.exit("Kein gültiges Eingabeverzeichnis gefunden.")

    observations = _load_results(run_dirs)
    if not observations:
        sys.exit("Keine Datenpunkte aus den angegebenen Verzeichnissen lesbar.")
    averaged = _average(observations)

    repeated = {k: v["n"] for k, v in averaged.items() if v["n"] > 1}
    print(f"{len(averaged)} eindeutige (P,I)-Koordinaten aus {len(run_dirs)} Verzeichnis(sen), "
          f"{sum(v['n'] for v in averaged.values())} Einzelmessungen insgesamt.")
    if repeated:
        print(f"{len(repeated)} Koordinate(n) mehrfach gemessen (gemittelt):")
        for (p, i), n in sorted(repeated.items()):
            print(f"  P delta={p:+.2f}, I delta={i:+.2f}: n={n}")

    best_key = min(averaged, key=lambda k: averaged[k]["ise"])
    print(f"\nBester Punkt (nach gemitteltem ISE): P delta={best_key[0]:+.2f}, "
          f"I delta={best_key[1]:+.2f}, ISE={averaged[best_key]['ise']:.0f} "
          f"(n={averaged[best_key]['n']})")

    timestamp = time.strftime("%Y-%m-%d_%H%M%S")
    out_dir = REPO_ROOT / "runs" / f"{timestamp}_heatmap"
    out_dir.mkdir(parents=True, exist_ok=True)

    _write_heatmap_csv(averaged, out_dir / "heatmap_data.csv")
    _make_heatmap(averaged, "ise", "ISE-Heatmap (gemittelt über alle Läufe)",
                  out_dir / "heatmap_ise.png", best_key)
    _make_heatmap(averaged, "mssd_2s", "MSSD-Heatmap, erste 2s (gemittelt)",
                  out_dir / "heatmap_mssd_2s.png", best_key)
    _make_heatmap(averaged, "mssd_full", "MSSD-Heatmap, gesamte 7s (gemittelt)",
                  out_dir / "heatmap_mssd_full.png", best_key)

    print(f"\nHeatmaps + Daten in {out_dir}")


if __name__ == "__main__":
    main()
