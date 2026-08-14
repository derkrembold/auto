"""Static analysis over raspi/'s logging system output files (see
watchdog/CLAUDE.md's log-format section) -- flags protocol-level
anomalies after the fact instead of relying on catching them live by
eye. Read-only: only opens and parses already-written .log files, never
touches the LIN bus, the watchdog's socket, or the motor -- no consent
needed (see raspi/CLAUDE.md's Motor Execution Consent).

Two line formats both come out of logsetup.py-based logging, at
different protocol layers, and are both understood here:
  - linbus-level (watchdog.log only): "[client]/[poll]  -> read NAME"
    / "... <- read NAME  ret=N  data=[...]" / "... -> write NAME data=[...]"
    -- either linbus line may carry an optional trailing "(ANNOTATION)"
    (e.g. linbus.py's write_bad_checksum(): "... (DELIBERATELY BAD
    CHECKSUM)"), tolerated but not otherwise interpreted here.
  - command-level (motorcontrol.py/validate_speed.py/
    capture_step_response.py): "-> <command>" / "<- <reply text>"

Checks:
  1. Unmatched `->` calls -- a call that never got a matching `<-`
     reply (the exact signature of the 2026-08-11 bus hang).
  2. `ret != 0` -- calls that did get a reply, but an error one.
  3. Latency -- `->`-to-`<-` gap exceeding --latency-threshold-ms.
  4. Data length -- `data=[...]` byte count vs. addresses.json's
     `bytes` field for that message name. Only checked on linbus-level
     lines -- command-level replies (e.g. motorcontrol.py's `hal`) also
     carry a `data=[...]`, but under a command word, not a message
     name, so there's nothing in addresses.json to check it against.
  5. WARNING/ERROR lines -- read from the log level field itself (added
     to logsetup.LOG_FORMAT 2026-08-12), not text-pattern guessing.
     Logs from before that change carry no level field, so this check
     silently finds nothing on them -- expected, not a bug here.
  6. Poll-loop cadence -- idle gaps on the watchdog's own [poll] thread
     between one call's reply and the next call's start, exceeding
     --poll-gap-threshold-ms (watchdog.log only -- [client] gaps are
     human/script-paced and not a cadence signal).

Usage:
    python3 analyze_logs.py watchdog.log motorcontrol.log ...
    python3 analyze_logs.py --addresses ../addresses.json watchdog.log

Exit code 0 if no anomalies were found across all given files, 1
otherwise -- lets a caller/skill check "clean or not" without parsing
the printed report.
"""
import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

LATENCY_THRESHOLD_MS = 50
POLL_GAP_THRESHOLD_MS = 1500

LINE_RE = re.compile(
    r"^(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})\.(?P<ms>\d{3})\s\s"
    r"(?:(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+)?(?P<rest>.*)$"
)
LINBUS_OPEN_RE = re.compile(
    r"^\[(?P<tag>client|poll)\]\s+-> (?P<kind>read|write)\s+(?P<name>\S+)"
    r"(?:\s+data=(?P<data>\[.*\]))?(?:\s+\([^)]*\))?\s*$"
)
LINBUS_CLOSE_RE = re.compile(
    r"^\[(?P<tag>client|poll)\]\s+<- read\s+(?P<name>\S+)\s+"
    r"ret=(?P<ret>-?\d+)\s+data=(?P<data>\[.*\])(?:\s+\([^)]*\))?\s*$"
)
CMD_OPEN_RE = re.compile(r"^-> (?P<cmd>.+)$")
CMD_CLOSE_RE = re.compile(r"^<- (?P<reply>.*)$")
RET_RE = re.compile(r"\bret=(-?\d+)\b")
BYTE_RE = re.compile(r"0x[0-9a-fA-F]{2}")


@dataclass
class Finding:
    line_no: int
    timestamp: str
    kind: str
    message: str


def load_addresses(path):
    messages = json.loads(Path(path).read_text())["messages"]
    return {m["name"]: m["bytes"] for m in messages}


def _byte_count(data_text):
    return len(BYTE_RE.findall(data_text))


def _check_length(addresses, name, data_text, line_no, ts_str, findings):
    if addresses is None or data_text is None:
        return
    expected = addresses.get(name)
    if expected is None:
        return  # unknown message name -- nothing to check against
    actual = _byte_count(data_text)
    if actual != expected:
        findings.append(Finding(
            line_no, ts_str, "length",
            f"{name}: data has {actual} byte(s), addresses.json says {expected}"))


def analyze(path, addresses=None,
            latency_threshold_ms=LATENCY_THRESHOLD_MS,
            poll_gap_threshold_ms=POLL_GAP_THRESHOLD_MS):
    findings = []
    open_calls = {}      # tag -> (line_no, ts_str, ts_seconds, name)
    last_idle_ts = {}    # tag -> ts_seconds of the last completed call
    counts = {"read": 0, "write": 0}

    for line_no, line in enumerate(Path(path).read_text().splitlines(), start=1):
        m = LINE_RE.match(line)
        if not m:
            continue
        ts = (int(m["h"]) * 3600 + int(m["m"]) * 60 + int(m["s"])
              + int(m["ms"]) / 1000)
        ts_str = f"{m['h']}:{m['m']}:{m['s']}.{m['ms']}"
        rest = m["rest"]

        if m["level"] in ("WARNING", "ERROR"):
            findings.append(Finding(line_no, ts_str, "level", f"{m['level']}: {rest}"))

        lb_open = LINBUS_OPEN_RE.match(rest)
        lb_close = None if lb_open else LINBUS_CLOSE_RE.match(rest)
        cmd_open = None if (lb_open or lb_close) else CMD_OPEN_RE.match(rest)
        cmd_close = None if (lb_open or lb_close or cmd_open) else CMD_CLOSE_RE.match(rest)

        if lb_open:
            tag, kind, name = lb_open["tag"], lb_open["kind"], lb_open["name"]
            counts[kind] += 1
            if tag == "poll" and tag in last_idle_ts:
                gap_ms = (ts - last_idle_ts[tag]) * 1000
                if gap_ms > poll_gap_threshold_ms:
                    findings.append(Finding(
                        line_no, ts_str, "poll_gap",
                        f"{gap_ms:.0f}ms idle before this call "
                        f"(> {poll_gap_threshold_ms}ms)"))
            if kind == "read":
                if tag in open_calls:
                    prev = open_calls[tag]
                    findings.append(Finding(
                        prev[0], prev[1], "unmatched",
                        f"[{tag}] {prev[3]} never got a reply before "
                        f"the next call started"))
                open_calls[tag] = (line_no, ts_str, ts, name)
            else:  # write -- no reply expected, by LIN protocol design
                _check_length(addresses, name, lb_open["data"], line_no, ts_str, findings)
                last_idle_ts[tag] = ts

        elif lb_close:
            tag, name, ret = lb_close["tag"], lb_close["name"], int(lb_close["ret"])
            open_call = open_calls.pop(tag, None)
            if open_call is None or open_call[3] != name:
                findings.append(Finding(
                    line_no, ts_str, "orphan_reply",
                    f"[{tag}] <- {name} with no matching -> call"))
            else:
                duration_ms = (ts - open_call[2]) * 1000
                if duration_ms > latency_threshold_ms:
                    findings.append(Finding(
                        line_no, ts_str, "latency",
                        f"[{tag}] {name} took {duration_ms:.1f}ms "
                        f"(> {latency_threshold_ms}ms)"))
            if ret != 0:
                findings.append(Finding(line_no, ts_str, "ret_nonzero", f"[{tag}] {name} ret={ret}"))
            _check_length(addresses, name, lb_close["data"], line_no, ts_str, findings)
            last_idle_ts[tag] = ts

        elif cmd_open:
            if "_cmd" in open_calls:
                prev = open_calls["_cmd"]
                findings.append(Finding(
                    prev[0], prev[1], "unmatched",
                    f"{prev[3]!r} never got a reply before the next call started"))
            open_calls["_cmd"] = (line_no, ts_str, ts, cmd_open["cmd"])

        elif cmd_close:
            reply = cmd_close["reply"]
            open_call = open_calls.pop("_cmd", None)
            if open_call is None:
                findings.append(Finding(
                    line_no, ts_str, "orphan_reply", f"<- {reply!r} with no matching -> call"))
            else:
                duration_ms = (ts - open_call[2]) * 1000
                if duration_ms > latency_threshold_ms:
                    findings.append(Finding(
                        line_no, ts_str, "latency",
                        f"{open_call[3]!r} took {duration_ms:.1f}ms "
                        f"(> {latency_threshold_ms}ms)"))
            ret_match = RET_RE.search(reply)
            if ret_match and int(ret_match.group(1)) != 0:
                cmd = open_call[3] if open_call else "?"
                findings.append(Finding(line_no, ts_str, "ret_nonzero", f"{cmd!r} -> {reply!r}"))

    # anything still open at EOF never got a reply
    for tag, (line_no, ts_str, _ts, name) in open_calls.items():
        label = f"[{tag}] {name}" if tag != "_cmd" else repr(name)
        findings.append(Finding(line_no, ts_str, "unmatched", f"{label} never got a reply (end of log)"))

    findings.sort(key=lambda f: f.line_no)
    return findings, counts


_KIND_LABELS = {
    "unmatched": "Unmatched calls (no reply received)",
    "orphan_reply": "Replies with no matching call",
    "ret_nonzero": "Non-zero ret codes",
    "latency": "Calls exceeding the latency threshold",
    "length": "data=[...] length mismatches vs addresses.json",
    "level": "WARNING / ERROR log lines",
    "poll_gap": "Poll-loop cadence gaps",
}


def format_report(path, findings, counts):
    lines = [f"=== {path} ===",
             f"{counts['read']} read call(s), {counts['write']} write call(s)"]
    if not findings:
        lines.append("no anomalies found")
        return "\n".join(lines)

    by_kind = {}
    for f in findings:
        by_kind.setdefault(f.kind, []).append(f)
    for kind, label in _KIND_LABELS.items():
        items = by_kind.get(kind)
        if not items:
            continue
        lines.append(f"\n{label}: {len(items)}")
        for f in items:
            lines.append(f"  line {f.line_no}  {f.timestamp}  {f.message}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("logs", nargs="+", help="log file(s) to analyze")
    parser.add_argument("--addresses", default=None,
                         help="path to addresses.json (default: repo root, "
                              "auto-detected relative to this script)")
    parser.add_argument("--latency-threshold-ms", type=float, default=LATENCY_THRESHOLD_MS)
    parser.add_argument("--poll-gap-threshold-ms", type=float, default=POLL_GAP_THRESHOLD_MS)
    args = parser.parse_args(argv)

    addresses_path = args.addresses
    if addresses_path is None:
        default_path = Path(__file__).resolve().parent.parent / "addresses.json"
        addresses_path = default_path if default_path.exists() else None
    addresses = load_addresses(addresses_path) if addresses_path else None

    any_findings = False
    for log_path in args.logs:
        findings, counts = analyze(log_path, addresses=addresses,
                                    latency_threshold_ms=args.latency_threshold_ms,
                                    poll_gap_threshold_ms=args.poll_gap_threshold_ms)
        print(format_report(log_path, findings, counts))
        print()
        any_findings = any_findings or bool(findings)

    return 1 if any_findings else 0


if __name__ == "__main__":
    sys.exit(main())
