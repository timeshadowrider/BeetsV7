#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v7.5 Inbox Watcher

Changes from v7.4:
- Recursive inotify watching. The original watcher only called add_watch()
  once on /inbox itself. inotify_simple.add_watch() is NOT recursive, so
  events inside /inbox/Artist/Album/ were never seen. The debounce timer
  could only fire if something touched /inbox directly (e.g. a new artist
  folder being created), but file-level changes inside existing subfolders
  were completely invisible.

  Fix: walk the inbox tree at startup and add a watch on every subdirectory.
  Also handle IN_CREATE events for new directories and add watches to them
  dynamically so newly-created subfolders are also watched.

- pipeline_running flag is now checked inside run_pipeline() with a proper
  guard rather than a bare global read, preventing a subtle race where two
  debounce timers could both pass the running check before either sets it.
"""

import os
import subprocess
import time
from pathlib import Path
from threading import Timer, Lock
from inotify_simple import INotify, flags

INBOX = Path("/inbox")
SETTLE_SECONDS = 180   # 3 minutes of no changes before running pipeline
PIPELINE = ["python3", "/app/scripts/pipeline_controller_v7.py"]

# Global debounce timer
debounce_timer = None

# FIX: Use a Lock to prevent two timers racing through the running check
_pipeline_lock = Lock()
pipeline_running = False


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def run_pipeline():
    global pipeline_running

    # FIX: acquire lock before checking/setting the flag to close the race window
    with _pipeline_lock:
        if pipeline_running:
            log("[SKIP] Pipeline already running")
            return
        pipeline_running = True

    log("=== Running v7 Pipeline Controller ===")
    try:
        subprocess.run(PIPELINE, check=True)
    except Exception as e:
        log(f"[ERROR] Pipeline failed: {e}")
    finally:
        with _pipeline_lock:
            pipeline_running = False
    log("=== Pipeline Finished ===")


def debounce_pipeline():
    global debounce_timer

    if debounce_timer:
        debounce_timer.cancel()

    debounce_timer = Timer(SETTLE_SECONDS, run_pipeline)
    debounce_timer.daemon = True
    debounce_timer.start()
    log(f"[DEBOUNCE] Pipeline scheduled in {SETTLE_SECONDS}s")


def add_watch(inotify, path: Path, wd_map: dict, watch_flags):
    """Add an inotify watch for path and record it in wd_map."""
    try:
        wd = inotify.add_watch(str(path), watch_flags)
        wd_map[wd] = path
        return wd
    except Exception as e:
        log(f"[WATCH] Could not watch {path}: {e}")
        return None


def main():
    log("=== v7.5 Watcher Started ===")
    log(f"Watching: {INBOX}")

    inotify = INotify()
    watch_flags = (
        flags.CREATE
        | flags.MODIFY
        | flags.MOVED_TO
        | flags.MOVED_FROM
        | flags.DELETE
        | flags.CLOSE_WRITE
    )

    # wd -> Path mapping so we can resolve which directory an event came from
    wd_map = {}

    # FIX: Add watches recursively for all existing subdirectories at startup.
    # inotify_simple.add_watch() is not recursive — only the exact directory
    # passed receives events. Previously only /inbox was watched, so file
    # activity inside /inbox/Artist/Album/ was completely invisible.
    INBOX.mkdir(parents=True, exist_ok=True)
    for dirpath, dirnames, _ in os.walk(str(INBOX)):
        add_watch(inotify, Path(dirpath), wd_map, watch_flags)

    log(f"[WATCH] Watching {len(wd_map)} directories")

    while True:
        try:
            events = inotify.read(timeout=5000)  # 5 second timeout so we stay responsive
        except Exception as e:
            log(f"[ERROR] inotify read failed: {e}")
            time.sleep(1)
            continue

        for event in events:
            name = event.name or ""

            # Ignore hidden/system files
            if name.startswith("."):
                continue

            # FIX: If a new directory was created, add a watch for it
            # so files placed inside it are also observed.
            if event.mask & flags.CREATE and event.mask & flags.ISDIR:
                parent = wd_map.get(event.wd)
                if parent:
                    new_dir = parent / name
                    add_watch(inotify, new_dir, wd_map, watch_flags)
                    log(f"[WATCH] Added watch for new dir: {new_dir} (total: {len(wd_map)})")

            log(f"[EVENT] {name} (mask={event.mask:#010x})")
            debounce_pipeline()


if __name__ == "__main__":
    main()