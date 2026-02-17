#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SLSKD Integration Module (Fixed for v0.24.3 API)

Handles communication with SLSKD (Soulseek daemon) to detect active transfers
and prevent processing of folders that are still being downloaded.
"""

import time
import requests
from pathlib import Path
from .logging import log, vlog
from .util import INBOX
from .fuzzy import tokenize, fuzzy_match


# Exponential backoff delays for retries
SLSKD_RETRY_DELAYS = [2, 4, 8]

# Hybrid settle threshold
SLSKD_GLOBAL_THRESHOLD = 5  # Allow up to 5 concurrent downloads
SLSKD_GLOBAL_WAIT = 20

# API configuration
SLSKD_API_KEY = "PV1RixwWGOi91oVYfSMhd7JNVy1hj6jpcBOcdM+z1mKB+JnIQ2c4nwVWLgYi2JHd"
SLSKD_HOST = "http://10.0.0.100:5030"


def slskd_get_transfers():
    """
    Get active downloads from SLSKD API.
    
    Returns:
        list: List of user objects with transfer data, or None on failure
    """
    # FIXED: Use correct endpoint for SLSKD v0.24.3
    url = f"{SLSKD_HOST}/api/v0/transfers/downloads"
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
            vlog(f"[SLSKD] HTTP error (attempt {attempt}/{len(SLSKD_RETRY_DELAYS)}): {e}")
            if attempt < len(SLSKD_RETRY_DELAYS):
                time.sleep(delay)
                
        except requests.exceptions.JSONDecodeError as e:
            vlog(f"[SLSKD] JSON decode error: {e}")
            if attempt < len(SLSKD_RETRY_DELAYS):
                time.sleep(delay)
                
        except requests.exceptions.ConnectionError as e:
            vlog(f"[SLSKD] Connection error: {e}")
            if attempt < len(SLSKD_RETRY_DELAYS):
                time.sleep(delay)
                
        except Exception as e:
            vlog(f"[SLSKD] Retry after error: {e}")
            if attempt < len(SLSKD_RETRY_DELAYS):
                time.sleep(delay)
    
    log("[SLSKD] All retries failed, treating SLSKD as busy.")
    return None


def slskd_active_transfers():
    """
    Get list of active (non-completed) transfer filenames.
    
    Parses the SLSKD API response structure:
    - Array of users
    - Each user has directories
    - Each directory has files
    - Each file has a state
    
    OPTION 2 FIX: Only counts ACTIVELY DOWNLOADING files, not queued ones.
    This prevents the pipeline from waiting forever on stuck queues.
    
    Returns:
        list: List of file paths that are currently being downloaded
    """
    transfers = slskd_get_transfers()
    if not transfers:
        return []
    
    active = []
    
    # OPTION 2: Only count ACTIVELY DOWNLOADING files, not queued ones
    # This prevents the pipeline from waiting forever on stuck queues
    incomplete_states = {
        "initializing",
        "inprogress",
    }
    
    # Parse the nested structure: users -> directories -> files
    for user in transfers:
        username = user.get("username", "unknown")
        directories = user.get("directories", [])
        
        for directory in directories:
            dir_path = directory.get("directory", "")
            files = directory.get("files", [])
            
            for file in files:
                state = file.get("state", "").lower()
                filename = file.get("filename", "")
                
                # Check if transfer is still active
                if any(s in state for s in incomplete_states):
                    if filename:
                        active.append(filename)
                        vlog(f"[SLSKD] Active: {username} - {filename} ({state})")
    
    if active:
        log(f"[SLSKD] Found {len(active)} active transfers")
    
    return active


def global_settle():
    """
    Wait until global SLSKD activity is below threshold.
    
    Continuously checks SLSKD for active transfers and waits until
    the number of active transfers falls below SLSKD_GLOBAL_THRESHOLD.
    
    OPTION 3 FIX: Includes a timeout to prevent infinite waiting on stuck queues.
    
    Returns:
        list: List of currently active transfer paths when settled
    """
    max_wait_time = 600  # OPTION 3: 10 minutes maximum wait
    start_time = time.time()
    
    while True:
        active = slskd_active_transfers()
        count = len(active)
        
        # OPTION 3: Timeout protection - don't wait forever
        elapsed = time.time() - start_time
        if elapsed > max_wait_time:
            log(f"[SLSKD] Timeout after {elapsed:.0f}s - proceeding anyway ({count} active)")
            return active
        
        if count > SLSKD_GLOBAL_THRESHOLD:
            log(f"[SLSKD] Global busy ({count} active). Waiting {SLSKD_GLOBAL_WAIT}s...")
            time.sleep(SLSKD_GLOBAL_WAIT)
            continue
        
        if count > 0:
            log(f"[SLSKD] {count} active transfers (below threshold)")
        else:
            log("[SLSKD] No active transfers")
            
        return active


def artist_in_use(artist_folder: Path, active_paths):
    """
    Check if artist folder matches any active SLSKD transfers.
    
    Uses fuzzy matching to compare folder name against active transfer paths.
    This prevents processing folders that are still being downloaded.
    
    Args:
        artist_folder: Path to the artist folder in /inbox
        active_paths: List of active transfer paths from SLSKD
        
    Returns:
        bool: True if the folder matches an active transfer
    """
    if not active_paths:
        return False
        
    folder_tokens = tokenize(artist_folder.name)
    
    for path in active_paths:
        path_tokens = tokenize(path)
        if fuzzy_match(path_tokens, folder_tokens):
            vlog(f"[SLSKD] Artist '{artist_folder.name}' matches active transfer: {path}")
            return True
    
    return False