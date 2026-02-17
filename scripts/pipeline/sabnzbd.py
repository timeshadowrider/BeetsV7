#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SABnzbd Integration Module - v7.4

Fixes:
- Only block on genuinely active statuses (not Paused/Failed which could
  block the pipeline forever on a stuck job)
- Improved path matching - checks multiple path components not just the last
- Better logging showing which job triggered the block
"""

import requests
from pathlib import Path

from .logging import log, vlog

SABNZBD_URL = "http://10.0.0.100:8080/api"
SABNZBD_API_KEY = "5c938b2911c14463a435cea4964679bc"

# Only block pipeline for these statuses
# Paused/Failed/Completed should NOT block processing
ACTIVE_STATUSES = {
    "Downloading",
    "Verifying",
    "Repairing",
    "Extracting",
    "Moving",
    "Running",  # Post-processing script running
}


def sabnzbd_is_processing(artist_folder: Path) -> bool:
    """
    Check if SABnzbd is actively processing a job related to this artist folder.

    FIX: Only blocks on genuinely active statuses.
    FIX: Checks multiple path components for more reliable matching.

    Returns:
        bool: True if SABnzbd is actively processing this artist
    """
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

            # Only block on active statuses
            if status not in ACTIVE_STATUSES:
                continue

            # FIX: Check storage path more thoroughly
            storage = job.get("storage", "")
            if storage:
                storage_path = Path(storage)
                # Check any path component matches artist folder name
                path_parts_lower = [p.lower() for p in storage_path.parts]
                if artist_name_lower in path_parts_lower:
                    vlog("[SABNZBD] Active job ({}) matches artist: {}".format(
                        status, artist_folder.name))
                    return True

            # Also check job filename/title as fallback
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
