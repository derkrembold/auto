"""Convert a Saleae Hall-channel capture (raw digital.csv export) into
an rpm-over-time trace. See analysis/CLAUDE.md's Hall-Edge RPM
Conversion section for the derivation and the debounce-noise finding
this implements a fix for.
"""

import csv
import os

# 24 Hall edges (single-bit Gray-code transitions, summed across all 3
# Hall channels) = 1 mechanical revolution -- matches the STM32
# firmware's own RPMFACTOR derivation, see STM32/CLAUDE.md's RPM
# Measurement Resolution section.
DEFAULT_EDGES_PER_REV = 24

# Raw high-bandwidth captures show single-sample-wide spikes (electrical
# ringing/EMI during commutation) that revert within ~100ns -- far
# shorter than any genuine Hall dwell time. Segments shorter than this
# are merged into their predecessor rather than counted as edges.
DEFAULT_DEBOUNCE_S = 1e-6

DEFAULT_HALL_COLUMNS = ("Channel 0", "Channel 1", "Channel 2")

# main.c's getState() -- (H1,H2,H3) == (PC0,PC1,PC2) as ("0"/"1" CSV
# strings) -> 6-step commutation state. 000/111 aren't in this table
# (getState() itself returns 6, its "invalid" sentinel) -- see
# STM32/CLAUDE.md's Commutation & Control section.
STATE_MAP = {
    ("1", "0", "0"): 4,
    ("1", "0", "1"): 5,
    ("0", "0", "1"): 0,
    ("0", "1", "1"): 1,
    ("0", "1", "0"): 2,
    ("1", "1", "0"): 3,
}

# Cyclic order of valid states -- each neighbor differs by exactly one
# Hall bit (derived from STATE_MAP above, cross-checked against
# driveStep()'s own CW state-advance table in main.c). A real Hall
# transition should always move to an adjacent entry in this cycle,
# either direction; anything else means a state was skipped.
STATE_CYCLE = [4, 5, 0, 1, 2, 3]


def capture_available(csv_path):
    """True if a Saleae digital.csv export exists at csv_path. The
    Saleae is a lab-only tool (root CLAUDE.md's Data Flow section) --
    most runs won't have a capture. Callers should check this (or use
    hall_rpm_from_csv()'s None return) instead of assuming one exists."""
    return os.path.isfile(csv_path)


def cleaned_hall_states(csv_path, hall_columns=DEFAULT_HALL_COLUMNS, debounce_s=DEFAULT_DEBOUNCE_S):
    """Read a Saleae raw digital.csv export and return the debounced
    Hall-state sequence as (timestamp, hall_tuple) pairs, one entry per
    confirmed state change (including the initial state at index 0)."""
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        time_col = reader.fieldnames[0]
        rows = [
            (float(row[time_col]), tuple(row[c] for c in hall_columns))
            for row in reader
        ]

    if not rows:
        return []

    confirmed = [rows[0]]
    for t, hall in rows[1:]:
        if hall != confirmed[-1][1]:
            confirmed.append((t, hall))

    cleaned = [confirmed[0]]
    i = 1
    while i < len(confirmed):
        t, hall = confirmed[i]
        dur = (confirmed[i + 1][0] - t) if i + 1 < len(confirmed) else float("inf")
        if dur < debounce_s:
            i += 2  # drop this spike and its reverting partner
            continue
        if hall != cleaned[-1][1]:
            cleaned.append((t, hall))
        i += 1

    return cleaned


def hall_edge_times(csv_path, hall_columns=DEFAULT_HALL_COLUMNS, debounce_s=DEFAULT_DEBOUNCE_S):
    """Read a Saleae raw digital.csv export and return debounced Hall
    transition timestamps (seconds, capture-relative)."""
    cleaned = cleaned_hall_states(csv_path, hall_columns=hall_columns, debounce_s=debounce_s)
    return [t for t, _ in cleaned[1:]]


def find_skipped_states(csv_path, hall_columns=DEFAULT_HALL_COLUMNS, debounce_s=DEFAULT_DEBOUNCE_S):
    """Check the debounced Hall-state sequence for missed commutation
    steps -- a real Hall interrupt firing late/not at all would show up
    as a jump to a non-adjacent state in STATE_CYCLE, or a landing on an
    invalid 000/111 combination. Returns a list of dicts, one per
    anomaly, each with t, prev_state, new_state, hall_before, hall_after."""
    cleaned = cleaned_hall_states(csv_path, hall_columns=hall_columns, debounce_s=debounce_s)
    anomalies = []
    prev_state = STATE_MAP.get(cleaned[0][1]) if cleaned else None
    for t, hall in cleaned[1:]:
        new_state = STATE_MAP.get(hall)
        if new_state is None:
            anomalies.append({
                "t": t, "prev_state": prev_state, "new_state": None,
                "hall_before": None, "hall_after": hall,
                "reason": f"invalid Hall combination {hall}",
            })
        elif prev_state is not None:
            i_prev = STATE_CYCLE.index(prev_state)
            i_new = STATE_CYCLE.index(new_state)
            step = (i_new - i_prev) % len(STATE_CYCLE)
            if step not in (1, len(STATE_CYCLE) - 1):
                anomalies.append({
                    "t": t, "prev_state": prev_state, "new_state": new_state,
                    "hall_before": None, "hall_after": hall,
                    "reason": f"non-adjacent jump {prev_state}->{new_state}",
                })
        if new_state is not None:
            prev_state = new_state
    return anomalies


def rpm_from_edges(edge_times, bin_s=0.1, edges_per_rev=DEFAULT_EDGES_PER_REV, t0=0.0, t1=None):
    """Bin edge timestamps into fixed windows and convert edge count per
    bin into rpm. Returns (bin_center_times, rpm_values)."""
    if not edge_times and t1 is None:
        return [], []

    t_max = t1 if t1 is not None else max(edge_times)
    n_bins = max(int((t_max - t0) / bin_s) + 1, 1)
    counts = [0] * n_bins
    for t in edge_times:
        idx = int((t - t0) / bin_s)
        if 0 <= idx < n_bins:
            counts[idx] += 1

    centers = [t0 + (i + 0.5) * bin_s for i in range(n_bins)]
    rpms = [c / edges_per_rev * (60 / bin_s) for c in counts]
    return centers, rpms


def find_sustained_high_edge(csv_path, column="Channel 3", min_duration_s=0.5):
    """Return the timestamp where `column` in a Saleae digital.csv
    export first goes HIGH and stays HIGH for at least min_duration_s,
    or None if it never does -- distinguishes a genuine trigger-pin
    event (held HIGH for seconds, see STM32/CLAUDE.md's Motor Control &
    Trigger Pin section) from a false trigger caused by the ~100ns EMI
    spikes documented in this file's module docstring (see
    saleae/CLAUDE.md's Trigger pin Open Point for the `rising`-trigger
    false-fire this guards against, since `pulse_high` turned out not
    to work as a hardware-level filter). Also usable to auto-align a
    `timed`-mode capture's clock to a motor-command log's clock, since
    the trigger edge and the `cntl3mot` write that raised it are the
    same LIN transaction (see saleae-trigger-capture's Analyze step)."""
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        time_col = reader.fieldnames[0]
        rows = [(float(row[time_col]), row[column]) for row in reader]

    # The CSV is a sparse edge log across *all* enabled channels, not
    # just `column` -- collapse to column's own value changes first, or
    # the "next row" gap below measures the time to the next unrelated
    # channel's edge instead of column's own transition.
    segments = [rows[0]]
    for t, val in rows[1:]:
        if val != segments[-1][1]:
            segments.append((t, val))

    for i, (t, val) in enumerate(segments):
        if val != "1":
            continue
        t_end = segments[i + 1][0] if i + 1 < len(segments) else float("inf")
        if t_end - t >= min_duration_s:
            return t
    return None


def has_sustained_high(csv_path, column="Channel 3", min_duration_s=0.5):
    """True if `column` reaches a stable HIGH for at least
    min_duration_s at some point -- see find_sustained_high_edge()."""
    return find_sustained_high_edge(csv_path, column, min_duration_s) is not None


def hall_rpm_from_csv(
    csv_path,
    hall_columns=DEFAULT_HALL_COLUMNS,
    bin_s=0.1,
    debounce_s=DEFAULT_DEBOUNCE_S,
    edges_per_rev=DEFAULT_EDGES_PER_REV,
    t0=0.0,
    t1=None,
):
    """Saleae digital.csv -> (bin_center_times, rpm_values), or
    (None, None) if no capture exists at csv_path -- see
    capture_available(). Convenience wrapper combining
    hall_edge_times() + rpm_from_edges()."""
    if not capture_available(csv_path):
        return None, None
    edges = hall_edge_times(csv_path, hall_columns=hall_columns, debounce_s=debounce_s)
    return rpm_from_edges(edges, bin_s=bin_s, edges_per_rev=edges_per_rev, t0=t0, t1=t1)
