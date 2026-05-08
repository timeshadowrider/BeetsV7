#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SLSKD Integration Module - v7.4
"""

import os
import time
import requests
from pathlib import Path
from .logging import log, vlog
from .util import INBOX
from .fuzzy import tokenize, fuzzy_match


SLSKD_API_KEY = os.getenv("SLSKD_API_KEY", "")
SLSKD_HOST    = os.getenv("SLSKD_HOST",    "http://10.0.0.100:5030")

SLSKD_RETRY_DELAYS = [2, 4, 8]
SLSKD_GLOBAL_THRESHOLD = 0
SLSKD_GLOBAL_WAIT = 30

ACTIVE_STATES = {
    "requested",
    "initializing",
    "inprogress",
    "queued",
}

TERMINAL_STATES = {
    "completed",
}


def slskd_get_transfers():
    url = "{}/api/v0/transfers/downloads".format(SLSKD_HOST)
    headers = {"X-API-Key": SLSKD_API_KEY}

    for attempt, delay in enumerate(SLSKD_RETRY_DELAYS, 1):
        try:
            r = requests.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            return r.json()

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                vlog("[SLSKD] Endpoint not found - check SLSKD API version")
                return []
            elif e.response.status_code == 401:
                vlog("[SLSKD] Authentication failed - check API key")
                return []
            vlog("[SLSKD] HTTP error (attempt {}/{}): {}".format(
                attempt, len(SLSKD_RETRY_DELAYS), e))
            if attempt < len(SLSKD_RETRY_DELAYS):
                time.sleep(delay)

        except requests.exceptions.JSONDecodeError as e:
            vlog("[SLSKD] JSON decode error: {}".format(e))
            if attempt < len(SLSKD_RETRY_DELAYS):
                time.sleep(delay)

        except requests.exceptions.ConnectionError as e:
            vlog("[SLSKD] Connection error: {}".format(e))
            if attempt < len(SLSKD_RETRY_DELAYS):
                time.sleep(delay)

        except Exception as e:
            vlog("[SLSKD] Retry after error: {}".format(e))
            if attempt < len(SLSKD_RETRY_DELAYS):
                time.sleep(delay)

    log("[SLSKD] All retries failed, treating SLSKD as busy.")
    return None


def slskd_active_transfers():
    transfers = slskd_get_transfers()
    if not transfers:
        return []

    active = []

    for user in transfers:
        username = user.get("username", "unknown")
        directories = user.get("directories", [])

        for directory in directories:
            files = directory.get("files", [])

            for file in files:
                raw_state = file.get("state", "")
                state = raw_state.lower()
                filename = file.get("filename", "")

                if any(t in state for t in TERMINAL_STATES):
                    continue

                if any(s in state for s in ACTIVE_STATES):
                    if filename:
                        active.append(filename)
                        vlog("[SLSKD] Active: {} - {} ({})".format(
                            username, filename, raw_state))

    if active:
        log("[SLSKD] Found {} active/queued transfers".format(len(active)))

    return active


def global_settle():
    max_wait_time = 600
    start_time = time.time()

    while True:
        active = slskd_active_transfers()
        count = len(active)

        elapsed = time.time() - start_time
        if elapsed > max_wait_time:
            log("[SLSKD] Timeout after {:.0f}s - proceeding anyway ({} active)".format(
                elapsed, count))
            return active

        if count > SLSKD_GLOBAL_THRESHOLD:
            log("[SLSKD] {} active/queued transfers. Waiting {}s...".format(
                count, SLSKD_GLOBAL_WAIT))
            time.sleep(SLSKD_GLOBAL_WAIT)
            continue

        if count > 0:
            log("[SLSKD] {} transfers (below threshold)".format(count))
        else:
            log("[SLSKD] No active transfers")

        return active


def artist_in_use(artist_folder: Path, active_paths):
    if not active_paths:
        return False

    folder_tokens = tokenize(artist_folder.name)

    for path in active_paths:
        path_tokens = tokenize(path)
        if fuzzy_match(path_tokens, folder_tokens):
            vlog("[SLSKD] Artist '{}' matches active transfer: {}".format(
                artist_folder.name, path))
            return True

    return False
