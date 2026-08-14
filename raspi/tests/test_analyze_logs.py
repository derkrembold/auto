from analyze_logs import analyze, format_report, load_addresses

ADDRESSES = {"st2mot": 2, "st0cur": 4, "cntl3mot": 2}


def _kinds(findings):
    return [f.kind for f in findings]


def test_clean_linbus_log_has_no_findings(tmp_path):
    log = tmp_path / "watchdog.log"
    log.write_text(
        "09:50:00.000  DEBUG   [poll]    -> read  st2mot\n"
        "09:50:00.003  DEBUG   [poll]    <- read  st2mot     ret=0  data=['0x00', '0x00']\n"
        "09:50:00.003  DEBUG   [poll]    -> read  st0cur\n"
        "09:50:00.007  DEBUG   [poll]    <- read  st0cur     ret=0  data=['0x01', '0x02', '0x01', '0x02']\n"
        "09:50:01.008  DEBUG   [poll]    -> read  st2mot\n"
        "09:50:01.011  DEBUG   [poll]    <- read  st2mot     ret=0  data=['0x00', '0x00']\n"
    )
    findings, counts = analyze(log, addresses=ADDRESSES)
    assert findings == []
    assert counts == {"read": 3, "write": 0}


def test_unmatched_read_flagged_as_hang(tmp_path):
    log = tmp_path / "watchdog.log"
    log.write_text(
        "09:50:00.000  DEBUG   [poll]    -> read  st2mot\n"
        # no matching <- before the log ends -- the exact 2026-08-11 signature
    )
    findings, _ = analyze(log, addresses=ADDRESSES)
    assert _kinds(findings) == ["unmatched"]
    assert "st2mot" in findings[0].message


def test_unmatched_read_flagged_when_next_call_starts_first(tmp_path):
    log = tmp_path / "watchdog.log"
    log.write_text(
        "09:50:00.000  DEBUG   [poll]    -> read  st2mot\n"
        "09:50:01.000  DEBUG   [poll]    -> read  st0cur\n"
        "09:50:01.003  DEBUG   [poll]    <- read  st0cur     ret=0  data=['0x01', '0x02', '0x01', '0x02']\n"
    )
    findings, _ = analyze(log, addresses=ADDRESSES)
    assert _kinds(findings) == ["unmatched"]
    assert "st2mot" in findings[0].message


def test_orphan_reply_with_no_matching_call(tmp_path):
    log = tmp_path / "watchdog.log"
    log.write_text(
        "09:50:00.000  DEBUG   [poll]    <- read  st2mot     ret=0  data=['0x00', '0x00']\n"
    )
    findings, _ = analyze(log, addresses=ADDRESSES)
    assert _kinds(findings) == ["orphan_reply"]


def test_nonzero_ret_flagged_linbus(tmp_path):
    log = tmp_path / "watchdog.log"
    log.write_text(
        "09:50:00.000  DEBUG   [poll]    -> read  st0cur\n"
        "09:50:00.004  DEBUG   [poll]    <- read  st0cur     ret=-5  data=[]\n"
    )
    findings, _ = analyze(log, addresses=ADDRESSES)
    assert "ret_nonzero" in _kinds(findings)
    assert any("ret=-5" in f.message for f in findings)


def test_nonzero_ret_flagged_command_level(tmp_path):
    log = tmp_path / "validate_speed.log"
    log.write_text(
        "09:53:50.402  INFO    -> rpm\n"
        "09:53:50.407  INFO    <- OK ret=-5 rpm=None (hex=0x0000)\n"
    )
    findings, _ = analyze(log, addresses=ADDRESSES)
    assert _kinds(findings) == ["ret_nonzero"]


def test_command_level_ok_no_ret_field_is_not_flagged(tmp_path):
    log = tmp_path / "motorcontrol.log"
    log.write_text(
        "09:50:48.043  INFO    -> speed 0\n"
        "09:50:48.048  INFO    <- OK\n"
    )
    findings, _ = analyze(log, addresses=ADDRESSES)
    assert findings == []


def test_latency_violation_flagged(tmp_path):
    log = tmp_path / "watchdog.log"
    log.write_text(
        "09:50:00.000  DEBUG   [poll]    -> read  st2mot\n"
        "09:50:00.100  DEBUG   [poll]    <- read  st2mot     ret=0  data=['0x00', '0x00']\n"
    )
    findings, _ = analyze(log, addresses=ADDRESSES, latency_threshold_ms=50)
    assert _kinds(findings) == ["latency"]


def test_latency_within_threshold_not_flagged(tmp_path):
    log = tmp_path / "watchdog.log"
    log.write_text(
        "09:50:00.000  DEBUG   [poll]    -> read  st2mot\n"
        "09:50:00.010  DEBUG   [poll]    <- read  st2mot     ret=0  data=['0x00', '0x00']\n"
    )
    findings, _ = analyze(log, addresses=ADDRESSES, latency_threshold_ms=50)
    assert findings == []


def test_data_length_mismatch_flagged_on_read(tmp_path):
    log = tmp_path / "watchdog.log"
    log.write_text(
        "09:50:00.000  DEBUG   [poll]    -> read  st0cur\n"
        # st0cur should be 4 bytes per addresses.json -- only 2 here
        "09:50:00.004  DEBUG   [poll]    <- read  st0cur     ret=0  data=['0x01', '0x02']\n"
    )
    findings, _ = analyze(log, addresses=ADDRESSES)
    assert _kinds(findings) == ["length"]
    assert "st0cur" in findings[0].message


def test_data_length_mismatch_flagged_on_write(tmp_path):
    log = tmp_path / "watchdog.log"
    log.write_text(
        # cntl3mot should be 2 bytes -- 1 here
        "09:50:00.000  DEBUG   [client]  -> write cntl3mot   data=['0x00']\n"
    )
    findings, _ = analyze(log, addresses=ADDRESSES)
    assert _kinds(findings) == ["length"]


def test_annotated_write_line_still_parsed_and_counted(tmp_path):
    # linbus.py's write_bad_checksum() (added 2026-08-14) appends
    # "(DELIBERATELY BAD CHECKSUM)" after data=[...] -- must not be
    # silently dropped from parsing (was a real bug: the trailing text
    # broke LINBUS_OPEN_RE's `\s*$` anchor, so this line used to be
    # skipped entirely -- not counted, not length-checked).
    log = tmp_path / "watchdog.log"
    log.write_text(
        "09:50:00.000  DEBUG   [client]  -> write cntl3mot   data=['0x00', '0x00'] "
        "(DELIBERATELY BAD CHECKSUM)\n"
    )
    findings, counts = analyze(log, addresses=ADDRESSES)
    assert findings == []
    assert counts == {"read": 0, "write": 1}


def test_annotated_write_line_with_wrong_length_still_flagged(tmp_path):
    log = tmp_path / "watchdog.log"
    log.write_text(
        # cntl3mot should be 2 bytes -- 1 here
        "09:50:00.000  DEBUG   [client]  -> write cntl3mot   data=['0x00'] "
        "(DELIBERATELY BAD CHECKSUM)\n"
    )
    findings, _ = analyze(log, addresses=ADDRESSES)
    assert _kinds(findings) == ["length"]


def test_data_length_not_checked_without_addresses(tmp_path):
    log = tmp_path / "watchdog.log"
    log.write_text(
        "09:50:00.000  DEBUG   [poll]    -> read  st0cur\n"
        "09:50:00.004  DEBUG   [poll]    <- read  st0cur     ret=0  data=['0x01', '0x02']\n"
    )
    findings, _ = analyze(log, addresses=None)
    assert findings == []


def test_warning_line_flagged(tmp_path):
    log = tmp_path / "watchdog.log"
    log.write_text(
        "09:50:00.000  WARNING [poll]    no response from slave (st0cur)\n"
    )
    findings, _ = analyze(log, addresses=ADDRESSES)
    assert _kinds(findings) == ["level"]
    assert "WARNING" in findings[0].message


def test_error_line_flagged(tmp_path):
    log = tmp_path / "watchdog.log"
    log.write_text(
        "09:50:00.000  ERROR   monitor() crashed\n"
    )
    findings, _ = analyze(log, addresses=ADDRESSES)
    assert _kinds(findings) == ["level"]


def test_info_and_debug_lines_not_flagged_as_level_findings(tmp_path):
    log = tmp_path / "watchdog.log"
    log.write_text(
        "09:50:00.000  INFO    listening on /tmp/motorwatchdog.sock\n"
    )
    findings, _ = analyze(log, addresses=ADDRESSES)
    assert findings == []


def test_pre_levelname_format_still_parses(tmp_path):
    # Logs from before the 2026-08-12 levelname addition have no level
    # field at all -- everything except the level check must still work.
    log = tmp_path / "watchdog.log"
    log.write_text(
        "09:50:00.000  [poll]    -> read  st2mot\n"
        "09:50:00.100  [poll]    <- read  st2mot     ret=0  data=['0x00', '0x00']\n"
    )
    findings, counts = analyze(log, addresses=ADDRESSES, latency_threshold_ms=50)
    assert counts == {"read": 1, "write": 0}
    assert _kinds(findings) == ["latency"]


def test_poll_gap_flagged(tmp_path):
    log = tmp_path / "watchdog.log"
    log.write_text(
        "09:50:00.000  DEBUG   [poll]    -> read  st2mot\n"
        "09:50:00.003  DEBUG   [poll]    <- read  st2mot     ret=0  data=['0x00', '0x00']\n"
        "09:50:05.000  DEBUG   [poll]    -> read  st2mot\n"  # 5s gap
        "09:50:05.003  DEBUG   [poll]    <- read  st2mot     ret=0  data=['0x00', '0x00']\n"
    )
    findings, _ = analyze(log, addresses=ADDRESSES, poll_gap_threshold_ms=1500)
    assert _kinds(findings) == ["poll_gap"]


def test_normal_poll_cadence_not_flagged(tmp_path):
    log = tmp_path / "watchdog.log"
    log.write_text(
        "09:50:00.000  DEBUG   [poll]    -> read  st2mot\n"
        "09:50:00.003  DEBUG   [poll]    <- read  st2mot     ret=0  data=['0x00', '0x00']\n"
        "09:50:01.005  DEBUG   [poll]    -> read  st2mot\n"  # ~1s gap, normal
        "09:50:01.008  DEBUG   [poll]    <- read  st2mot     ret=0  data=['0x00', '0x00']\n"
    )
    findings, _ = analyze(log, addresses=ADDRESSES, poll_gap_threshold_ms=1500)
    assert findings == []


def test_client_gaps_are_not_subject_to_poll_gap_check(tmp_path):
    log = tmp_path / "watchdog.log"
    log.write_text(
        "09:50:00.000  DEBUG   [client]  -> read  st2mot\n"
        "09:50:00.003  DEBUG   [client]  <- read  st2mot     ret=0  data=['0x00', '0x00']\n"
        "09:50:30.000  DEBUG   [client]  -> read  st2mot\n"  # large gap, but human-paced
        "09:50:30.003  DEBUG   [client]  <- read  st2mot     ret=0  data=['0x00', '0x00']\n"
    )
    findings, _ = analyze(log, addresses=ADDRESSES, poll_gap_threshold_ms=1500)
    assert findings == []


def test_load_addresses_reads_bytes_field(tmp_path):
    addr_file = tmp_path / "addresses.json"
    addr_file.write_text(
        '{"messages": [{"name": "st2mot", "pid": "0x18", "bytes": 2, '
        '"source": "motor", "destination": "master"}]}'
    )
    assert load_addresses(addr_file) == {"st2mot": 2}


def test_format_report_no_findings(tmp_path):
    log = tmp_path / "watchdog.log"
    log.write_text(
        "09:50:00.000  DEBUG   [poll]    -> read  st2mot\n"
        "09:50:00.003  DEBUG   [poll]    <- read  st2mot     ret=0  data=['0x00', '0x00']\n"
    )
    findings, counts = analyze(log, addresses=ADDRESSES)
    report = format_report(str(log), findings, counts)
    assert "no anomalies found" in report


def test_format_report_groups_findings_by_kind(tmp_path):
    log = tmp_path / "watchdog.log"
    log.write_text(
        "09:50:00.000  WARNING [poll]    no response from slave (st0cur)\n"
    )
    findings, counts = analyze(log, addresses=ADDRESSES)
    report = format_report(str(log), findings, counts)
    assert "WARNING / ERROR log lines: 1" in report
