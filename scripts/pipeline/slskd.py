#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import requests
from pathlib import Path

from .logging import log, vlog
from .util import INBOX
from .fuzzy import tokenize, fuzzy_match

# Exponential backoff delays
SLSKD_RETRY_DELAYS = [2, 4, 8]

# Hybrid settle threshold
SLSKD_GLOBAL_THRESHOLD = 2
SLSKD_GLOBAL_WAIT = 20

# API key (replace with env var later if desired)
SLSKD_API_KEY = "PV1RixwWGOi91oVYfSMhd7JNVy1hj6jpcBOcdM+z1mKB+JnIQ2c4nwVWLgYi2JHd"


def slskd_get_transfers():
    url = "http://10.0.0.100:5030/api/v0/transfers"
    headers = {"X-API-Key": SLSKD_API_KEY}

    for delay in SLSKD_RETRY_DELAYS:
        try:
            r = requests.get(url, headers=headers, timeout=5)
            return r.json()
        except Exception as e:
            vlog("[SLSKD] Retry after error: %s" % e)
            time.sleep(delay)

    log("[SLSKD] All retries failed, treating SLSKD as busy.")
    return None


def slskd_active_transfers():
    transfers = slskd_get_transfers()
    if not transfers:
        return []

    active = []
    for t in transfers:
        state = t.get("state")
        path = t.get("path", "")
        if state not in ("completed", "succeeded"):
            active.append(path)
    return active


def global_settle():
    while True:
        active = slskd_active_transfers()
        count = len(active)

        if count > SLSKD_GLOBAL_THRESHOLD:
            log("[SLSKD] Global busy (%d active). Waiting %ds..." %
                (count, SLSKD_GLOBAL_WAIT))
            time.sleep(SLSKD_GLOBAL_WAIT)
            continue

        return active


def artist_in_use(artist_folder: Path, active_paths):
    folder_tokens = tokenize(artist_folder.name)

    for p in active_paths:
        path_tokens = tokenize(p)
        if fuzzy_match(path_tokens, folder_tokens):
            return True

    return False
