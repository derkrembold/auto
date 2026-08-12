"""Shared logging setup for raspi/ scripts — one rotating log file per
script, always at full detail, with an independent choice of whether
that same detail also echoes to the terminal. See
raspi/watchdog/CLAUDE.md's log-format notes for the design discussion
behind this (2026-08-12).

Deploy flattens raspi/control/ and raspi/watchdog/ into one directory on
the Pi (see raspi/CLAUDE.md's Deployment Pattern), so this is importable
from scripts in either folder — same as linbus.py/motorcontrol.py
already are across that boundary.
"""
import logging
import sys
from pathlib import Path

LOG_FORMAT = "%(asctime)s.%(msecs)03d  %(levelname)-7s %(message)s"
LOG_DATEFMT = "%H:%M:%S"


def rotate_log(path):
    # Keep exactly one generation of history instead of either unbounded
    # growth (always append) or losing evidence of a rare bug if a
    # restart happens before the log's been copied off (always
    # overwrite) — e.g. watchdog.log -> watchdog.log.1, then a fresh
    # watchdog.log starts. Overwrites any existing .1 from two restarts
    # ago; only one generation is kept, not a full history.
    path = Path(path)
    if path.exists():
        path.replace(path.with_name(path.name + ".1"))


def configure(logger_name, log_path, terminal_level=logging.INFO):
    # File handler: always attached, always DEBUG — the file gets full
    # detail unconditionally, so "forgot to enable verbose logging
    # before the rare bug happened" stops being possible. Terminal
    # handler is optional and independently leveled — pass
    # terminal_level=None for scripts whose stdout is reserved for
    # something else (e.g. validate_speed.py's CSV output), or
    # logging.DEBUG/INFO to control how much shows live.
    rotate_log(log_path)

    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()  # re-configuring (e.g. in tests) shouldn't stack handlers

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT)

    file_handler = logging.FileHandler(log_path)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if terminal_level is not None:
        # Explicit stdout, not logging's stderr default -- keeps this on
        # the same stream as any plain print() calls a script still
        # does (e.g. watchdog.py's spinner), so terminal ordering stays
        # sane instead of stdout/stderr interleaving unpredictably.
        stream_handler = logging.StreamHandler(stream=sys.stdout)
        stream_handler.setLevel(terminal_level)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    return logger
