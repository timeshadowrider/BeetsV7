#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import requests

from .util import LIBRARY
from .logging import log


def fix_library_permissions():
    """
    FIX: chown runs as appuser (uid 1000) which can only chown files it owns.
    Removed chown - it would silently fail or error on files owned by root.
    chmod is sufficient and works for owned files.
    """
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
    host = "http://10.0.0.100"
    port = 4533
    user = "timeshadowrider"
    password = "An|t@theR@bb|t"
    url = "%s:%s/rest/startScan" % (host, port)

    params = {"u": user, "p": password, "v": "1.13.0", "c": "beets", "f": "json"}

    try:
        log("[SUBSONIC] Triggering Navidrome scan at %s" % url)
        r = requests.get(url, params=params, timeout=10)
        log("[SUBSONIC] Response %s: %s" % (r.status_code, r.text[:200]))
    except requests.exceptions.ConnectionError:
        log("[SUBSONIC] Cannot connect to Navidrome - skipping scan")
    except Exception as e:
        log("[SUBSONIC] Scan trigger failed: %s" % e)


def trigger_volumio_rescan():
    """
    FIX: Added timeout to subprocess.run to prevent indefinite blocking
    if Volumio is unreachable.
    """
    try:
        log("[VOLUMIO] Triggering Volumio rescan...")
        result = subprocess.run(
            ["ssh",
             "-o", "ConnectTimeout=10",
             "-o", "StrictHostKeyChecking=no",
             "-o", "BatchMode=yes",
             "volumio@10.0.0.102",
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
