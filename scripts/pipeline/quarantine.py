#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
v7.3 Quarantine Module (Production Ready)

Rules:
- Only quarantine *finished* failed imports.
- Never touch _UNPACK_* folders (active SABnzbd/SLSKD downloads).
- Never touch folders still being written to (mtime settle).
- Never touch folders fuzzy-matched to active SLSKD transfers.
- Never touch folders SABnzbd is still processing.
- Never allow failed_imports to exist outside /music/quarantine.
- Never scan /inbox for failed_imports (they shouldn't exist there).
- Flatten quarantined files safely.
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


def qlog(msg: str):
    line = "[%s] [quarantine] %s" % (_ts(), msg)
    print(line)
    log("[quarantine] %s" % msg)


def sanitize_for_filename(text: str) -> str:
    illegal = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    for ch in illegal:
        text = text.replace(ch, '-')
    return text


def flatten_quarantine_filename(original_path: Path) -> str:
    """
    Convert nested paths into a single safe filename.
    Example:
        Artist/Album/track01.flac
    becomes:
        Artist - Album - track01.flac
    """
    parts = [p for p in original_path.parts if p not in ("", "/", FAILED_IMPORTS_NAME)]
    filename = " - ".join(parts)
    return sanitize_for_filename(filename)


def _safe_delete(src: Path):
    """
    Delete a file safely. If it cannot be deleted, mark it as .stuck.
    """
    try:
        os.remove(src)
        return
    except PermissionError:
        try:
            os.chmod(src, 0o666)
            os.remove(src)
            return
        except Exception as e:
            qlog("WARNING: could not delete %s: %s" % (src, e))
    except Exception as e:
        qlog("WARNING: could not delete %s: %s" % (src, e))

    # Last resort: mark as stuck
    try:
        stuck = src.with_suffix(src.suffix + ".stuck")
        src.rename(stuck)
        qlog("Marked as stuck: %s" % stuck)
    except Exception as e:
        qlog("WARNING: could not mark %s as stuck: %s" % (src, e))


def quarantine_folder(src_folder: Path):
    """
    Move all files from a failed_imports folder into the quarantine root.
    Flatten nested paths into safe filenames.
    """
    if not src_folder.exists():
        return

    QUARANTINE_ROOT.mkdir(parents=True, exist_ok=True)

    for root, dirs, files in os.walk(src_folder):
        for f in files:
            src = Path(root) / f

            if not src.exists():
                continue

            rel = src.relative_to(src_folder.parent)
            flat_name = flatten_quarantine_filename(rel)
            dst = QUARANTINE_ROOT / flat_name

            dst.parent.mkdir(parents=True, exist_ok=True)

            qlog("QUARANTINE: %s -> %s" % (src, dst))

            try:
                shutil.copy2(src, dst)
            except Exception as e:
                qlog("WARNING: could not copy %s: %s" % (src, e))

            _safe_delete(src)

    try:
        shutil.rmtree(src_folder, ignore_errors=True)
    except Exception as e:
        qlog("WARNING: could not remove folder %s: %s" % (src_folder, e))


def quarantine_failed_imports_global(root_path: Path):
    """
    Scan root_path for any folder named failed_imports.
    Apply full safety checks:
    - skip /inbox entirely (failed_imports should never exist there)
    - skip _UNPACK_* (active downloads)
    - skip SABnzbd active jobs
    - skip SLSKD fuzzy matches
    - skip folders not settled (mtime)
    """
    if not root_path.exists():
        return
    
    # SAFETY: Never scan /inbox for failed_imports
    # Failed imports should only exist in /pre-library (temporarily)
    # and /music/quarantine (permanently)
    root_path_str = str(root_path.resolve())
    if root_path_str.startswith("/inbox"):
        qlog("SKIP: /inbox should never contain failed_imports folders")
        return

    qlog("Scanning for failed_imports under: %s" % root_path)

    active_slsk_paths = slskd_active_transfers()

    for current_root, dirs, files in os.walk(root_path):
        for d in list(dirs):
            folder = Path(current_root) / d

            # Skip active download folders
            if d.startswith("_UNPACK_"):
                vlog("[quarantine] SKIP active download folder: %s" % folder)
                continue

            # Only process failed_imports folders
            if d != FAILED_IMPORTS_NAME:
                continue

            qlog("FOUND failed_imports folder: %s" % folder)

            # Safety Check 1: SABnzbd
            if sabnzbd_is_processing(folder):
                qlog("SKIP: SABnzbd still processing %s" % folder)
                continue

            # Safety Check 2: SLSKD fuzzy match
            if artist_in_use(folder, active_slsk_paths):
                qlog("SKIP: SLSKD active match for %s" % folder)
                continue

            # Safety Check 3: mtime settle
            if not folder_is_settled(folder, 300):
                qlog("SKIP: folder not settled %s" % folder)
                continue

            # Passed all safety checks ? quarantine it
            quarantine_folder(folder)

            # Prevent recursion
            dirs.remove(d)
