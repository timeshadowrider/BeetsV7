#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import subprocess

from .util import LIBRARY
from .logging import log


def fix_library_permissions():
    try:
        log("[PERMISSIONS] Fixing library permissions...")
        subprocess.run(
            ["find", str(LIBRARY), "-type", "d", "-exec", "chmod", "755", "{}", "+"],
            check=False, timeout=60
        )
        subprocess.run(
            ["find", str(LIBRARY), "-type", "f", "-exec", "chmod", "644", "{}", "+"],
            check=False, timeout=60
        )
        log("[PERMISSIONS] Library permissions corrected.")
    except subprocess.TimeoutExpired:
        log("[PERMISSIONS] WARNING: chmod timed out on large library")
    except Exception as e:
        log("[PERMISSIONS] ERROR: %s" % e)


