#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import subprocess
import requests

from .util import LIBRARY
from .logging import log

SUBSONIC_HOST     = os.getenv("SUBSONIC_HOST",     "http://10.0.0.100")
SUBSONIC_PORT     = os.getenv("SUBSONIC_PORT",     "4533")
SUBSONIC_USER     = os.getenv("SUBSONIC_USER",     "")
SUBSONIC_PASSWORD = os.getenv("SUBSONIC_PASSWORD", "")

VOLUMIO_MPD_HOST  = os.getenv("VOLUMIO_MPD_HOST",  "10.0.0.102")


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


def trigger_subsonic_scan_from_config():
    url = "%s:%s/rest/startScan" % (SUBSONIC_HOST, SUBSONIC_PORT)
    params = {
        "u": SUBSONIC_USER,
        "p": SUBSONIC_PASSWORD,
        "v": "1.13.0",
        "c": "beets",
        "f": "json",
    }

    try:
        log("[SUBSONIC] Triggering Navidrome scan at %s" % url)
        r = requests.get(url, params=params, timeout=10)
        log("[SUBSONIC] Response %s: %s" % (r.status_code, r.text[:200]))
    except requests.exceptions.ConnectionError:
        log("[SUBSONIC] Cannot connect to Navidrome - skipping scan")
    except Exception as e:
        log("[SUBSONIC] Scan trigger failed: %s" % e)


def trigger_volumio_rescan():
    try:
        log("[VOLUMIO] Triggering Volumio rescan...")
        result = subprocess.run(
            ["ssh",
             "-o", "ConnectTimeout=10",
             "-o", "StrictHostKeyChecking=no",
             "-o", "BatchMode=yes",
             "volumio@%s" % VOLUMIO_MPD_HOST,
             "volumio", "rescan"],
            check=False,
            timeout=30,
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            log("[VOLUMIO] Rescan triggered.")
        else:
            log("[VOLUMIO] Rescan returned code %d: %s" % (result.returncode, result.stderr[:200]))
    except subprocess.TimeoutExpired:
        log("[VOLUMIO] SSH timeout - Volumio may be unreachable")
    except Exception as e:
        log("[VOLUMIO] ERROR triggering rescan: %s" % e)
