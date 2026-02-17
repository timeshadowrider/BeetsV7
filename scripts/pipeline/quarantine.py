#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Quarantine Module - v7.4

Fixes:
- quarantine_folder now uses shutil.move instead of copy+delete
  to prevent duplicate files if delete fails after successful copy
- flatten_quarantine_filename adds a timestamp suffix to prevent
  silent overwrites when two files have the same flattened name
- Never scan /inbox for failed_imports
"""

import os
import shutil
import time
from pathlib import Path

from .logging import log, vlog
from .sabnzbd import sabnzbd_is_processing
from .slskd import slskd_active_transfers, artist_in_use
from .settle import folder_is_settled


FAILED_IMPORTS_NAME = "failed_imports"
QUARANTINE_ROOT = Path("/music/quarantine/failed_imports")


def _ts():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _ts_short():
    return time.strftime("%Y%m%d_%H%M%S")


def qlog(msg: str):
    line = "[%s] [quarantine] %s" % (_ts(), msg)
    print(line)
    log("[quarantine] %s" % msg)


def sanitize_for_filename(text: str) -> str:
    illegal = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    for ch in illegal:
        text = text.replace(ch, '-')
    return text


def flatten_quarantine_filename(original_path: Path, timestamp: str) -> str:
    """
    Convert nested paths into a single safe filename.
    FIX: Adds timestamp to prevent silent overwrites of same-named files.

    Example:
        Artist/Album/track01.flac + 20240101_120000
    becomes:
        Artist - Album - track01 - 20240101_120000.flac
    """
    parts = [p for p in original_path.parts if p not in ("", "/", FAILED_IMPORTS_NAME)]
    # Keep extension separate so timestamp goes before it
    if parts:
        last = parts[-1]
        p = Path(last)
        stem = p.stem
        suffix = p.suffix
        parts[-1] = "%s - %s%s" % (stem, timestamp, suffix)
    filename = " - ".join(parts)
    return sanitize_for_filename(filename)


def quarantine_folder(src_folder: Path):
    """
    Move all files from a failed_imports folder into the quarantine root.
    FIX: Uses shutil.move instead of copy+delete to prevent duplicates.
    FIX: Timestamp per-run prevents filename collisions.
    """
    if not src_folder.exists():
        return

    QUARANTINE_ROOT.mkdir(parents=True, exist_ok=True)
    timestamp = _ts_short()

    for root, dirs, files in os.walk(src_folder):
        for f in files:
            src = Path(root) / f

            if not src.exists():
                continue

            rel = src.relative_to(src_folder.parent)
            flat_name = flatten_quarantine_filename(rel, timestamp)
            dst = QUARANTINE_ROOT / flat_name

            dst.parent.mkdir(parents=True, exist_ok=True)

            qlog("QUARANTINE: %s -> %s" % (src, dst))

            try:
                # FIX: Use move instead of copy+delete
                shutil.move(str(src), str(dst))
            except Exception as e:
                qlog("WARNING: could not move %s: %s" % (src, e))

    try:
        shutil.rmtree(src_folder, ignore_errors=True)
    except Exception as e:
        qlog("WARNING: could not remove folder %s: %s" % (src_folder, e))


def quarantine_failed_imports_global(root_path: Path):
    """
    Scan root_path for any folder named failed_imports and quarantine them.
    Applies full safety checks before touching anything.
    """
    if not root_path.exists():
        return

    # SAFETY: Never scan /inbox
    root_path_str = str(root_path.resolve())
    if root_path_str.startswith("/inbox"):
        qlog("SKIP: /inbox should never contain failed_imports folders")
        return

    qlog("Scanning for failed_imports under: %s" % root_path)

    active_slsk_paths = slskd_active_transfers()

    for current_root, dirs, files in os.walk(root_path):
        for d in list(dirs):
            folder = Path(current_root) / d

            if d.startswith("_UNPACK_"):
                vlog("[quarantine] SKIP active download folder: %s" % folder)
                continue

            if d != FAILED_IMPORTS_NAME:
                continue

            qlog("FOUND failed_imports folder: %s" % folder)

            if sabnzbd_is_processing(folder):
                qlog("SKIP: SABnzbd still processing %s" % folder)
                continue

            if artist_in_use(folder, active_slsk_paths):
                qlog("SKIP: SLSKD active match for %s" % folder)
                continue

            if not folder_is_settled(folder, 300):
                qlog("SKIP: folder not settled %s" % folder)
                continue

            quarantine_folder(folder)
            dirs.remove(d)
