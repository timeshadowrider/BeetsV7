#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import requests

from .util import LIBRARY
from .logging import log


def fix_library_permissions():
    try:
        log("[PERMISSIONS] Fixing library permissions...")
        subprocess.run(["chown", "-R", "1000:1000", str(LIBRARY)], check=False)
        subprocess.run(["find", str(LIBRARY), "-type", "d", "-exec", "chmod", "2777", "{}", "+"], check=False)
        subprocess.run(["find", str(LIBRARY), "-type", "f", "-exec", "chmod", "0666", "{}", "+"], check=False)
        log("[PERMISSIONS] Library permissions corrected.")
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
    except Exception as e:
        log("[SUBSONIC] Scan trigger failed: %s" % e)


def trigger_volumio_rescan():
    try:
        log("[VOLUMIO] Triggering Volumio rescan...")
        subprocess.run(["ssh", "volumio@10.0.0.102", "volumio", "rescan"], check=False)
        log("[VOLUMIO] Rescan triggered.")
    except Exception as e:
        log("[VOLUMIO] ERROR triggering rescan: %s" % e)
