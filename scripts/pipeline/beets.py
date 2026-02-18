#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Beets Integration Module - v7.5

Changes from v7.4:
- run_beets_import: added --log flag so beets writes per-import rejection
  reasons to /data/last_beets_imports.log (separate from pipeline.log)
- run_post_import: broadened 'added:-1h..' to 'added:-24h..' so imports
  that take longer than one hour are still caught by the update/move pass
- verify_import_success: now also warns when failed_imports count > 0,
  and points to BEETS_IMPORT_LOG for diagnosis
"""
from .util import run, PRELIB, LIBRARY
from .logging import vlog, log
from pathlib import Path

# FIX: These are suffix patterns for Path.suffix comparisons, NOT glob patterns.
# Use lowercase extensions with leading dot, not "*.flac" glob syntax.
AUDIO_EXTS = {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aac"}

# Glob patterns used only where Path.glob() is called
AUDIO_GLOBS = ["**/*.flac", "**/*.mp3", "**/*.m4a", "**/*.ogg", "**/*.wav", "**/*.aac"]

# Import log -- beets writes per-album rejection reasons here, separate from pipeline.log.
# Check this file first when diagnosing why albums end up in failed_imports.
BEETS_IMPORT_LOG = "/data/last_beets_imports.log"


def run_fingerprint():
    """Run AcoustID fingerprinting on all files in /pre-library."""
    vlog("[FP] Running fingerprint pass...")
    if not PRELIB.exists() or not any(PRELIB.iterdir()):
        vlog("[FP] No files in /pre-library to fingerprint")
        return
    try:
        run(["python3", "/app/scripts/fingerprint_all.py"])
        vlog("[FP] Fingerprinting completed")
    except Exception as e:
        log("[FP] Warning: Fingerprinting failed: %s" % e)


def run_beets_import():
    """
    Import files from /pre-library to /music/library.
    Uses --quiet so Beets is non-interactive but still respects
    quiet_fallback and none_rec_action from config.yaml (set to 'asis').

    FIX: Added --log flag so beets writes per-album rejection reasons to
    /data/last_beets_imports.log. Without this, failed imports are silent
    in pipeline.log -- you can see counts via verify_import_success() but
    not the actual cause (duplicate, no match, below threshold, etc.).
    """
    vlog("[BEETS] Importing pre-library...")
    if not PRELIB.exists() or not any(PRELIB.iterdir()):
        vlog("[BEETS] No files in /pre-library to import")
        return
    try:
        run(["beet", "import", "--quiet", "--log=%s" % BEETS_IMPORT_LOG, str(PRELIB)])
        vlog("[BEETS] Import completed")

        # Diagnostic: log any files still in /pre-library (outside failed_imports)
        remaining = []
        for pattern in AUDIO_GLOBS:
            for f in PRELIB.glob(pattern):
                if "failed_imports" not in str(f):
                    remaining.append(f)

        if remaining:
            log("[BEETS] Warning: %d files still in /pre-library after import:" % len(remaining))
            for f in remaining[:10]:
                log("[BEETS]   %s" % f)
            if len(remaining) > 10:
                log("[BEETS]   ... and %d more" % (len(remaining) - 10))
        else:
            vlog("[BEETS] All files successfully moved from /pre-library")

    except Exception as e:
        log("[BEETS] Import error: %s" % e)


def run_post_import():
    """
    Post-import updates scoped to recently added files.

    FIX: Broadened query from 'added:-1h..' to 'added:-24h..' to catch
    imports from long-running sessions that exceed the 1-hour window.
    A large import batch (hundreds of albums) can easily take 2-4 hours,
    meaning everything before the last hour was silently missing the
    update/move pass and left with incorrect paths or stale metadata.
    """
    vlog("[BEETS] Post-import update/move...")
    try:
        vlog("[BEETS] Updating recently imported files (24h window)...")
        run(["beet", "update", "added:-24h.."])
        vlog("[BEETS] Ensuring files are in correct location (24h window)...")
        run(["beet", "move", "added:-24h.."])
        vlog("[BEETS] Post-import completed")
    except Exception as e:
        log("[BEETS] Post-import warning: %s" % e)

    verify_import_success()


def verify_import_success():
    """Log import statistics after each run."""
    stats = {
        "prelib_remaining": 0,
        "library_total": 0,
        "failed_imports": 0,
    }

    if PRELIB.exists():
        for pattern in AUDIO_GLOBS:
            for f in PRELIB.glob(pattern):
                if "failed_imports" not in str(f):
                    stats["prelib_remaining"] += 1

    if LIBRARY.exists():
        for pattern in AUDIO_GLOBS:
            stats["library_total"] += len(list(LIBRARY.glob(pattern)))

    failed_dir = PRELIB / "failed_imports"
    if failed_dir.exists():
        for pattern in AUDIO_GLOBS:
            stats["failed_imports"] += len(list(failed_dir.glob(pattern)))

    log("[VERIFY] Import Statistics:")
    log("[VERIFY]   Library total:         %d files" % stats["library_total"])
    log("[VERIFY]   Pre-library remaining: %d files" % stats["prelib_remaining"])
    log("[VERIFY]   Failed imports:        %d files" % stats["failed_imports"])

    if stats["prelib_remaining"] > 0:
        log("[VERIFY] WARNING: Files still in /pre-library - check %s" % BEETS_IMPORT_LOG)

    if stats["failed_imports"] > 0:
        log("[VERIFY] WARNING: %d files in failed_imports - check %s" % (
            stats["failed_imports"], BEETS_IMPORT_LOG))

    return stats


if __name__ == "__main__":
    log("[BEETS] Running beets module directly...")
    run_fingerprint()
    run_beets_import()
    run_post_import()
    log("[BEETS] Done.")