#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Beets Metadata Refresh Script
Runs all metadata plugins on a schedule to keep library up-to-date.

Features:
- Fetches missing album art
- Updates lyrics
- Syncs with MusicBrainz
- Embeds artwork
- Updates genres
- Triggers Plex/MPD updates
- Generates smart playlists
"""

import subprocess
import time
from datetime import datetime
from pathlib import Path
import logging

# Configure logging
LOG_FILE = Path("/data/metadata_refresh.log")
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def run_beet_command(command: str, description: str, timeout: int = 3600):
    """
    Run a beet command and log the result.
    
    Args:
        command: Beet command to run (e.g., "beet fetchart")
        description: Human-readable description
        timeout: Command timeout in seconds (default: 1 hour)
    
    Returns:
        bool: True if successful, False otherwise
    """
    logger.info(f"[START] {description}")
    logger.info(f"[CMD] {command}")
    
    start_time = time.time()
    
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False
        )
        
        elapsed = time.time() - start_time
        
        if result.returncode == 0:
            logger.info(f"[SUCCESS] {description} (took {elapsed:.1f}s)")
            if result.stdout.strip():
                logger.debug(f"[OUTPUT] {result.stdout[:500]}")
            return True
        else:
            logger.warning(f"[FAILED] {description} (exit code {result.returncode})")
            if result.stderr.strip():
                logger.error(f"[ERROR] {result.stderr[:500]}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error(f"[TIMEOUT] {description} exceeded {timeout}s")
        return False
    except Exception as e:
        logger.error(f"[ERROR] {description}: {e}")
        return False


def fetch_missing_artwork():
    """Fetch missing album artwork from various sources."""
    logger.info("=" * 60)
    logger.info("FETCHING MISSING ARTWORK")
    logger.info("=" * 60)
    
    # Fetch art for albums without covers
    run_beet_command(
        "beet fetchart",
        "Fetch missing album art"
    )
    
    # Force re-fetch for albums with poor quality art (optional)
    # Uncomment if you want to replace low-quality covers
    # run_beet_command(
    #     "beet fetchart -f",
    #     "Force re-fetch all album art"
    # )


def embed_artwork():
    """Embed album artwork into audio files."""
    logger.info("=" * 60)
    logger.info("EMBEDDING ARTWORK")
    logger.info("=" * 60)
    
    run_beet_command(
        "beet embedart -y",
        "Embed artwork into files"
    )


def fetch_lyrics():
    """Fetch missing lyrics."""
    logger.info("=" * 60)
    logger.info("FETCHING LYRICS")
    logger.info("=" * 60)
    
    # Fetch lyrics for songs without them
    run_beet_command(
        "beet lyrics",
        "Fetch missing lyrics"
    )
    
    # Force re-fetch lyrics (optional)
    # Uncomment to update all lyrics
    # run_beet_command(
    #     "beet lyrics -f",
    #     "Force re-fetch all lyrics"
    # )


def sync_musicbrainz():
    """Sync metadata with MusicBrainz database."""
    logger.info("=" * 60)
    logger.info("SYNCING WITH MUSICBRAINZ")
    logger.info("=" * 60)
    
    # Update metadata from MusicBrainz
    run_beet_command(
        "beet mbsync",
        "Sync metadata with MusicBrainz"
    )


def update_genres():
    """Update genre tags from Last.fm."""
    logger.info("=" * 60)
    logger.info("UPDATING GENRES")
    logger.info("=" * 60)
    
    run_beet_command(
        "beet lastgenre",
        "Update genre tags from Last.fm"
    )


def scrub_metadata():
    """Clean and normalize metadata tags."""
    logger.info("=" * 60)
    logger.info("SCRUBBING METADATA")
    logger.info("=" * 60)
    
    run_beet_command(
        "beet scrub",
        "Scrub and normalize metadata"
    )


def update_albumtypes():
    """Update album type metadata."""
    logger.info("=" * 60)
    logger.info("UPDATING ALBUM TYPES")
    logger.info("=" * 60)
    
    run_beet_command(
        "beet albumtypes",
        "Update album type metadata"
    )


def generate_smart_playlists():
    """Generate smart playlists based on queries."""
    logger.info("=" * 60)
    logger.info("GENERATING SMART PLAYLISTS")
    logger.info("=" * 60)
    
    run_beet_command(
        "beet splupdate",
        "Update smart playlists"
    )


def update_plex():
    """Trigger Plex library update."""
    logger.info("=" * 60)
    logger.info("UPDATING PLEX")
    logger.info("=" * 60)
    
    run_beet_command(
        "beet plexupdate",
        "Trigger Plex library update"
    )


def update_mpd():
    """Trigger MPD database update."""
    logger.info("=" * 60)
    logger.info("UPDATING MPD")
    logger.info("=" * 60)
    
    run_beet_command(
        "beet mpdupdate",
        "Trigger MPD database update"
    )


def run_full_refresh():
    """
    Run complete metadata refresh cycle.
    
    Order of operations:
    1. Sync with MusicBrainz (get latest metadata)
    2. Update album types
    3. Fetch missing artwork
    4. Embed artwork into files
    5. Fetch missing lyrics
    6. Update genres
    7. Scrub/clean metadata
    8. Generate smart playlists
    9. Notify media servers (Plex, MPD)
    """
    start_time = time.time()
    
    logger.info("+" + "=" * 58 + "+")
    logger.info("¦" + " " * 10 + "BEETS METADATA REFRESH STARTED" + " " * 17 + "¦")
    logger.info("¦" + f" Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}" + " " * 30 + "¦")
    logger.info("+" + "=" * 58 + "+")
    
    # Phase 1: Metadata Updates
    logger.info("\n>>> PHASE 1: METADATA UPDATES <<<\n")
    sync_musicbrainz()
    update_albumtypes()
    
    # Phase 2: Artwork
    logger.info("\n>>> PHASE 2: ARTWORK <<<\n")
    fetch_missing_artwork()
    embed_artwork()
    
    # Phase 3: Lyrics & Genres
    logger.info("\n>>> PHASE 3: LYRICS & GENRES <<<\n")
    fetch_lyrics()
    update_genres()
    
    # Phase 4: Cleanup
    logger.info("\n>>> PHASE 4: CLEANUP <<<\n")
    scrub_metadata()
    
    # Phase 5: Playlists & Notifications
    logger.info("\n>>> PHASE 5: PLAYLISTS & NOTIFICATIONS <<<\n")
    generate_smart_playlists()
    update_plex()
    update_mpd()
    
    # Summary
    elapsed = time.time() - start_time
    logger.info("+" + "=" * 58 + "+")
    logger.info("¦" + " " * 10 + "METADATA REFRESH COMPLETED" + " " * 21 + "¦")
    logger.info("¦" + f" Finished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}" + " " * 28 + "¦")
    logger.info("¦" + f" Total time: {elapsed / 60:.1f} minutes" + " " * 34 + "¦")
    logger.info("+" + "=" * 58 + "+")


def run_quick_refresh():
    """
    Run quick refresh - just artwork, lyrics, and server updates.
    Useful for more frequent runs.
    """
    start_time = time.time()
    
    logger.info(">>> QUICK REFRESH STARTED <<<")
    
    fetch_missing_artwork()
    embed_artwork()
    fetch_lyrics()
    generate_smart_playlists()
    update_plex()
    update_mpd()
    
    elapsed = time.time() - start_time
    logger.info(f">>> QUICK REFRESH COMPLETED ({elapsed / 60:.1f} minutes) <<<")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--quick":
        run_quick_refresh()
    else:
        run_full_refresh()