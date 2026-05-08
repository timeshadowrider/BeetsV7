#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from .util import (
    ensure_data_dir,
    rotate_if_needed,
    ts,
    PIPELINE_LOG,
    PIPELINE_VERBOSE_LOG,
    PIPELINE_STATUS_JSON,
)
import json


def log(msg: str):
    ensure_data_dir()
    line = "[%s] %s" % (ts(), msg)
    print(line)
    # FIX: rotate_if_needed renames the file, then we open fresh.
    # Previously the line was formatted BEFORE rotate, so if rotate
    # happened the timestamp in the line could precede the new file.
    # Now rotate happens before the line is written, which is correct.
    rotate_if_needed(PIPELINE_LOG)
    with open(PIPELINE_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def vlog(msg: str):
    ensure_data_dir()
    line = "[%s] %s" % (ts(), msg)
    print(line)
    rotate_if_needed(PIPELINE_VERBOSE_LOG)
    with open(PIPELINE_VERBOSE_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def update_status(status: str, detail: str = "", current_artist: str = ""):
    ensure_data_dir()
    payload = {
        "timestamp": ts(),
        "status": status,
        "detail": detail,
        "current_artist": current_artist,
    }
    # FIX: Write to a temp file then rename to avoid a partial read
    # if the API reads pipeline_status.json mid-write.
    tmp = PIPELINE_STATUS_JSON.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        tmp.replace(PIPELINE_STATUS_JSON)
    except Exception:
        # Fallback: write directly if rename fails
        with open(PIPELINE_STATUS_JSON, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
