#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import subprocess
from pathlib import Path

LIBRARY = Path("/music/library")
SETTLE_SECONDS = 60
SLEEP_SECONDS = 30

def run(cmd):
    print(f"[WATCHER] RUN: {' '.join(cmd)}")
    subprocess.run(cmd, check=False)

def folder_is_settled(path):
    newest = 0
    for root, dirs, files in os.walk(path):
        for f in files:
            fp = Path(root) / f
            try:
                m = fp.stat().st_mtime
                if m > newest:
                    newest = m
            except FileNotFoundError:
                pass

    if newest == 0:
        return True

    age = time.time() - newest
    return age >= SETTLE_SECONDS

def run_metadata_pass():
    print("[WATCHER] Running metadata refresh pass...")

    run(["beet", "fetchart", "-f"])
    run(["beet", "embedart", "-f"])
    run(["beet", "mbsync"])
    run(["beet", "lastgenre"])
    run(["beet", "lyrics"])
    run(["beet", "scrub"])
    run(["beet", "zero"])
    run(["beet", "update"])

    print("[WATCHER] Metadata refresh complete.")

def main():
    print("[WATCHER] Metadata watcher started.")

    last_mtime = 0

    while True:
        try:
            current_mtime = LIBRARY.stat().st_mtime

            if current_mtime != last_mtime:
                print("[WATCHER] Change detected in library.")
                last_mtime = current_mtime

                if folder_is_settled(LIBRARY):
                    run_metadata_pass()
                else:
                    print("[WATCHER] Library not settled yet, waiting...")

        except Exception as e:
            print(f"[WATCHER] ERROR: {e}")

        time.sleep(SLEEP_SECONDS)

if __name__ == "__main__":
    main()
