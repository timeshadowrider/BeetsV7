#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
from pathlib import Path

from .logging import vlog


def folder_is_settled(path: Path, min_age_seconds: int):
    newest_mtime = 0

    for root, dirs, files in os.walk(path):
        for f in files:
            try:
                mtime = (Path(root) / f).stat().st_mtime
                if mtime > newest_mtime:
                    newest_mtime = mtime
            except FileNotFoundError:
                pass

    if newest_mtime == 0:
        return True

    age = time.time() - newest_mtime
    vlog("SETTLE CHECK: %s age=%.1fs threshold=%ss" %
         (path, age, min_age_seconds))

    return age >= min_age_seconds
