#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
from pathlib import Path

from .logging import vlog


def folder_is_settled(path: Path, min_age_seconds: int) -> bool:
    """
    Check if a folder has been idle for at least min_age_seconds.
    FIX: Handles FileNotFoundError during walk (race condition protection).
    FIX: Returns True if folder disappears mid-check (treat as settled/gone).
    """
    newest_mtime = 0

    try:
        for root, dirs, files in os.walk(path):
            for f in files:
                try:
                    mtime = (Path(root) / f).stat().st_mtime
                    if mtime > newest_mtime:
                        newest_mtime = mtime
                except FileNotFoundError:
                    pass
    except FileNotFoundError:
        # Folder disappeared mid-walk - treat as settled (it's gone)
        vlog("SETTLE CHECK: %s disappeared during walk - treating as settled" % path)
        return True
    except Exception as e:
        vlog("SETTLE CHECK: %s error during walk: %s - treating as not settled" % (path, e))
        return False

    if newest_mtime == 0:
        return True

    age = time.time() - newest_mtime
    vlog("SETTLE CHECK: %s age=%.1fs threshold=%ss" % (path, age, min_age_seconds))

    return age >= min_age_seconds
