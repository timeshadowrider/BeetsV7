#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SABnzbd Integration Module - v7.4
"""

import os
import requests
from pathlib import Path

from .logging import log, vlog

SABNZBD_URL     = os.getenv("SABNZBD_URL",     "http://10.0.0.100:8080/api")
SABNZBD_API_KEY = os.getenv("SABNZBD_API_KEY", "")

ACTIVE_STATUSES = {
    "Downloading",
    "Verifying",
    "Repairing",
    "Extracting",
    "Moving",
    "Running",
}


def sabnzbd_is_processing(artist_folder: Path) -> bool:
    try:
        params = {
            "mode": "queue",
            "output": "json",
            "apikey": SABNZBD_API_KEY,
        }

        r = requests.get(SABNZBD_URL, params=params, timeout=5)
        data = r.json()

        artist_name_lower = artist_folder.name.lower()

        for job in data.get("queue", {}).get("slots", []):
            status = job.get("status", "")

            if status not in ACTIVE_STATUSES:
                continue

            storage = job.get("storage", "")
            if storage:
                storage_path = Path(storage)
                path_parts_lower = [p.lower() for p in storage_path.parts]
                if artist_name_lower in path_parts_lower:
                    vlog("[SABNZBD] Active job ({}) matches artist: {}".format(
                        status, artist_folder.name))
                    return True

            filename = job.get("filename", "").lower()
            if artist_name_lower in filename:
                vlog("[SABNZBD] Active job ({}) filename matches artist: {}".format(
                    status, artist_folder.name))
                return True

        return False

    except requests.exceptions.ConnectionError:
        vlog("[SABNZBD] Cannot connect - assuming not processing")
        return False
    except Exception as e:
        log("[SABNZBD] Error checking status: {}".format(e))
        return False
