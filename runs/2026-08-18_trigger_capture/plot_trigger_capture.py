import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, r"C:\Users\rembo\Documents\Auto")
from analysis.hall_rpm import hall_rpm_from_csv

MOTOR_CSV = "capture_step_response_attempt2.csv"
SALEAE_CSV = r"C:\Users\rembo\Documents\Auto\saleae\exports\trigger_capture_2026-08-18_attempt2\digital.csv"
OUT_PATH = "trigger_capture_hall_vs_lin_rpm.png"

lin_t, lin_rpm = [], []
with open(MOTOR_CSV) as f:
    for line in f:
        parts = line.strip().split(",")
        if len(parts) != 4 or not parts[0].isdigit():
            continue
        elapsed_ms, rpm = parts[0], parts[1]
        lin_t.append(int(elapsed_ms) / 1000)
        lin_rpm.append(int(rpm))

# trigger mode: Saleae capture-relative t=0 IS the trigger edge (the
# cntl3mot speed-nonzero write) -- same clock as elapsed_ms above,
# no offset to compute (unlike the earlier timed-mode captures).
hall_t, hall_rpm = hall_rpm_from_csv(SALEAE_CSV, bin_s=0.1, t0=0.0)

fig, ax = plt.subplots(figsize=(11, 6))
ax.step(lin_t, lin_rpm, where="mid", color="tab:blue", linewidth=1.5,
        label="LIN st2mot `rpm` (quantized /25, ~200ms poll)")
ax.plot(hall_t, hall_rpm, color="tab:orange", linewidth=1.2,
        marker=".", markersize=3,
        label="Saleae Hall-edge rpm (100ms bins, debounced, ground truth)")
ax.axhline(1000, color="gray", linestyle="--", linewidth=0.8, label="commanded speed=1000")
ax.axvline(0, color="green", linestyle=":", linewidth=1, label="trigger edge = speed 1000 sent")

ax.set_xlabel("time since trigger [s]")
ax.set_ylabel("rpm")
ax.set_title("Trigger-mode capture: LIN rpm vs. Saleae Hall-edge rpm (2026-08-18, attempt 2)")
ax.legend(loc="lower right", fontsize=9)
ax.grid(True, alpha=0.3)
fig.tight_layout()
fig.savefig(OUT_PATH, dpi=150)
print(f"wrote {OUT_PATH}")
print(f"lin samples: {len(lin_t)}, hall bins: {len(hall_t)}")
