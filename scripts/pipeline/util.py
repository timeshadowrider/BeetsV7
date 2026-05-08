#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import subprocess
import time
import os

# Core paths
INBOX = Path("/inbox")
PRELIB = Path("/pre-library")
LIBRARY = Path("/music/library")
DATA_DIR = Path("/data")

PIPELINE_LOG = DATA_DIR / "pipeline.log"
PIPELINE_VERBOSE_LOG = DATA_DIR / "pipeline_verbose.log"
PIPELINE_STATUS_JSON = DATA_DIR / "pipeline_status.json"

MAX_LOG_SIZE = 10 * 1024 * 1024


def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def rotate_if_needed(path: Path):
    if path.exists() and path.stat().st_size > MAX_LOG_SIZE:
        backup = path.with_suffix(path.suffix + ".1")
        if backup.exists():
            backup.unlink()
        path.rename(backup)


def ts():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def run(cmd):
    """
    Run a subprocess command and return the CompletedProcess result.

    FIX: Do NOT use capture_output=True - beet import needs stdin/stdout
    to function correctly in non-interactive mode. capture_output breaks
    beets' terminal detection and can cause hangs or incorrect behaviour.
    Instead stderr is redirected to stdout so it appears in container logs.
    """
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        from .logging import log
        log("[RUN] Command exited with code %d: %s" % (
            result.returncode, " ".join(str(c) for c in cmd)))
    return result


def safe_folder_name(text) -> str:
    return (text or "Unknown").replace("/", "-").strip()
