#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import time
from pathlib import Path
from threading import Timer
from inotify_simple import INotify, flags

INBOX = Path("/inbox")
SETTLE_SECONDS = 180   # 3 minutes of no changes before running pipeline
PIPELINE = [ "python3", "/app/scripts/pipeline_controller_v7.py" ]

# Global debounce timer
debounce_timer = None
pipeline_running = False


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def run_pipeline():
    global pipeline_running
    if pipeline_running:
        log("[SKIP] Pipeline already running")
        return

    pipeline_running = True
    log("=== Running v7 Pipeline Controller ===")

    try:
        subprocess.run(PIPELINE, check=True)
    except Exception as e:
        log(f"[ERROR] Pipeline failed: {e}")

    pipeline_running = False
    log("=== Pipeline Finished ===")


def debounce_pipeline():
    global debounce_timer

    # Cancel previous timer
    if debounce_timer:
        debounce_timer.cancel()

    # Start a new timer
    debounce_timer = Timer(SETTLE_SECONDS, run_pipeline)
    debounce_timer.start()
    log(f"[DEBOUNCE] Pipeline scheduled in {SETTLE_SECONDS} seconds")


def main():
    log("=== v7 Watcher Started ===")
    log(f"Watching: {INBOX}")

    inotify = INotify()
    watch_flags = flags.CREATE | flags.MODIFY | flags.MOVED_TO | flags.MOVED_FROM | flags.DELETE

    # Watch inbox recursively
    wd = inotify.add_watch(str(INBOX), watch_flags)

    while True:
        events = inotify.read()
        for event in events:
            # Ignore hidden/system files
            if event.name.startswith("."):
                continue

            log(f"[EVENT] {event.name} ({event.mask})")
            debounce_pipeline()


if __name__ == "__main__":
    main()
