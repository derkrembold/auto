import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, r"C:\Users\rembo\Documents\Auto")
from analysis.hall_rpm import find_sustained_high_edge, hall_rpm_from_csv

MOTOR_CSV = "capture_step_response_attempt2.csv"
DIGITAL_CSV = r"C:\Users\rembo\Documents\Auto\saleae\exports\trigger_capture_2026-08-18_attempt2\digital.csv"
OUT_PATH = "plot_via_skill.png"

# 1. Locate inputs -- done above.

# 2. Auto-align via the trigger pin's sustained-HIGH edge.
trigger_t = find_sustained_high_edge(DIGITAL_CSV)
if trigger_t is None:
    raise SystemExit("No sustained trigger-pin HIGH found in this capture -- stopping, not plotting misaligned data.")
print(f"trigger_t = {trigger_t:.4f}s")

# 3. Compute both rpm series, plus current (sparse -- skip blanks).
lin_t, lin_rpm = [], []
cur_t, cur_val1, cur_val2 = [], [], []
with open(MOTOR_CSV) as f:
    for line in f:
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

hall_t, hall_rpm = hall_rpm_from_csv(DIGITAL_CSV, bin_s=0.1, t0=0.0)
hall_t = [t - trigger_t for t in hall_t]

# 4. Plot and send.
fig, ax1 = plt.subplots(figsize=(11, 6))
l1, = ax1.step(lin_t, lin_rpm, where="mid", color="tab:blue", linewidth=1.5,
               label="LIN st2mot `rpm` (quantized /25, ~200ms poll)")
l2, = ax1.plot(hall_t, hall_rpm, color="tab:orange", linewidth=1.2,
               marker=".", markersize=3,
               label="Saleae Hall-edge rpm (100ms bins, debounced, ground truth)")
l3 = ax1.axhline(1000, color="gray", linestyle="--", linewidth=0.8, label="commanded speed=1000")
l4 = ax1.axvline(0, color="green", linestyle=":", linewidth=1, label=f"trigger edge (t={trigger_t:.3f}s in capture)")
ax1.set_xlabel("time since speed command [s]")
ax1.set_ylabel("rpm")

ax2 = ax1.twinx()
l5, = ax2.plot(cur_t, cur_val1, color="tab:red", marker="s", markersize=5,
               linewidth=1.2, label="current_val1 [A]")
l6, = ax2.plot(cur_t, cur_val2, color="tab:purple", marker="^", markersize=5,
               linewidth=1.2, label="current_val2 [A]")
ax2.set_ylabel("current [A]")

ax1.set_title("plot-saleae-step-response: trigger_capture_2026-08-18_attempt2")
ax1.legend(handles=[l1, l2, l3, l4, l5, l6], loc="lower right", fontsize=9)
ax1.grid(True, alpha=0.3)
fig.tight_layout()
fig.savefig(OUT_PATH, dpi=150)
print(f"wrote {OUT_PATH}")
