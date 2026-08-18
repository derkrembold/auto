import re
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, r"C:\Users\rembo\Documents\Auto")
from analysis.hall_rpm import hall_rpm_from_csv

LOG_PATH = "capture_step_response.log"
CSV_PATH = r"C:\Users\rembo\Documents\Auto\saleae\exports\step_response_trigger_test4\digital.csv"
OUT_PATH = "hall_vs_lin_rpm.png"

# Saleae capture-relative time at which the trigger pin (channel 3) went
# HIGH -- this is the same LIN transaction as the "speed 1000" write
# below, so it anchors the two independent timelines to a common t=0.
TRIGGER_HIGH_T = 4.035007200

TIME_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\.(\d{3})")


def parse_wall_time(line):
    m = TIME_RE.match(line)
    h, mi, s, ms = (int(x) for x in m.groups())
    return h * 3600 + mi * 60 + s + ms / 1000


# --- 1. LIN-reported rpm from capture_step_response.log ---
lin_t = []
lin_rpm = []
t_speed1000 = None
with open(LOG_PATH) as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if "-> speed 1000" in line:
        t_speed1000 = parse_wall_time(line)
        break

assert t_speed1000 is not None, "couldn't find 'speed 1000' command in log"

for line in lines:
    m = re.search(r"<- OK ret=0 rpm=(-?\d+)", line)
    if m:
        t = parse_wall_time(line)
        lin_t.append(t - t_speed1000)
        lin_rpm.append(int(m.group(1)))

# --- 2. Hall-edge-derived rpm from the Saleae capture ---
# Capture-relative timestamps -- shift into "seconds since speed 1000"
# to match lin_t below, same as TRIGGER_HIGH_T does throughout this file.
hall_bin_t_raw, hall_bin_rpm = hall_rpm_from_csv(CSV_PATH, bin_s=0.1, t0=0.0)
hall_bin_t = [t - TRIGGER_HIGH_T for t in hall_bin_t_raw]

# --- 3. Plot overlay ---
fig, ax = plt.subplots(figsize=(11, 6))
ax.step(lin_t, lin_rpm, where="mid", color="tab:blue", linewidth=1.5,
        label="LIN st2mot `rpm` (quantized /25, ~200ms poll)")
ax.plot(hall_bin_t, hall_bin_rpm, color="tab:orange", linewidth=1.2,
        marker=".", markersize=3,
        label="Saleae Hall-edge rpm (100ms bins, debounced, ground truth)")
ax.axhline(1000, color="gray", linestyle="--", linewidth=0.8, label="commanded speed=1000")
ax.axvline(0, color="green", linestyle=":", linewidth=1, label="speed 1000 sent")
stop_t = parse_wall_time([l for l in lines if "-> speed 0" in l][-1]) - t_speed1000
ax.axvline(stop_t, color="red", linestyle=":", linewidth=1, label="speed 0 sent")

ax.set_xlabel("time since 'speed 1000' command [s]")
ax.set_ylabel("rpm")
ax.set_title("LIN-reported rpm vs. Saleae Hall-edge rpm -- step_response_trigger_test4 (2026-08-17)")
ax.legend(loc="lower right", fontsize=9)
ax.grid(True, alpha=0.3)
fig.tight_layout()
fig.savefig(OUT_PATH, dpi=150)
print(f"wrote {OUT_PATH}")
print(f"lin samples: {len(lin_t)}, hall bins: {len(hall_bin_t)}")
