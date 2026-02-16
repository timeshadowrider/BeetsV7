#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
from pathlib import Path

from .logging import log, vlog


def sabnzbd_is_processing(artist_folder: Path) -> bool:
    try:
        url = "http://10.0.0.100:8080/api"
        params = {
            "mode": "queue",
            "output": "json",
            "apikey": "5c938b2911c14463a435cea4964679bc"
        }

        r = requests.get(url, params=params, timeout=5)
        data = r.json()

        for job in data.get("queue", {}).get("slots", []):
            if job.get("status") != "Completed":
                if Path(job.get("storage", "")).name == artist_folder.name:
                    vlog("[SABNZBD] Active job for %s" % artist_folder)
                    return True

        return False

    except Exception as e:
        log("[SABNZBD] Error checking status: %s" % e)
        return False
