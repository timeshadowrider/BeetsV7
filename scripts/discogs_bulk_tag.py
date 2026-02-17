#!/usr/bin/env python3
"""
discogs_bulk_tag.py - Bulk apply Discogs format descriptions to beets library

Searches Discogs for each album in your beets library and applies
meaningful format tags (Remastered, Deluxe Edition, etc.) to albumdisambig.

Usage:
    python3 discogs_bulk_tag.py [--dry-run] [--force] [--artist "Artist Name"]

Options:
    --dry-run     Show what would be changed without applying anything
    --force       Re-process albums that already have albumdisambig set
    --artist X    Only process albums by a specific artist
    --move        Run beet move after updating tags (renames folders)

Examples:
    python3 discogs_bulk_tag.py --dry-run
    python3 discogs_bulk_tag.py --artist "Eagles"
    python3 discogs_bulk_tag.py --move
"""

import sys
import time
import subprocess
import requests
import json
import argparse
import logging
from datetime import datetime

# Config
DISCOGS_TOKEN = "nSxVRTjzwbgIxzManORnSuDCIUEqouNYUcKymrHv"
DISCOGS_USER_AGENT = "BeetsV7BulkTagger/1.0"
LOG_FILE = "/data/discogs_bulk_tag.log"

# Discogs rate limit: 60 requests/min unauthenticated, 60/min authenticated
# We use 1 second between requests to be safe
REQUEST_DELAY = 1.1

# Only these terms will be written to albumdisambig
KEEP_TERMS = {
    "remastered",
    "deluxe edition",
    "limited edition",
    "numbered",
    "audiophile",
    "half-speed mastering",
    "direct metal mastering",
    "dmm",
    "sacd",
    "picture disc",
    "colored vinyl",
    "clear vinyl",
    "box set",
}

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger(__name__)


def discogs_search(artist, album):
    """Search Discogs for an album and return the best match release ID."""
    url = "https://api.discogs.com/database/search"
    headers = {
        "Authorization": "Discogs token={}".format(DISCOGS_TOKEN),
        "User-Agent": DISCOGS_USER_AGENT,
    }
    params = {
        "artist": artist,
        "release_title": album,
        "type": "release",
        "per_page": 5,
    }
    resp = requests.get(url, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    return results


def discogs_get_release(release_id):
    """Fetch full release details from Discogs."""
    url = "https://api.discogs.com/releases/{}".format(release_id)
    headers = {
        "Authorization": "Discogs token={}".format(DISCOGS_TOKEN),
        "User-Agent": DISCOGS_USER_AGENT,
    }
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()


def extract_format_tags(release):
    """Extract meaningful format descriptions from a Discogs release."""
    tags = []
    for fmt in release.get("formats", []):
        for desc in fmt.get("descriptions", []):
            lower = desc.lower().strip()
            if any(keep in lower for keep in KEEP_TERMS):
                tags.append(desc.strip())
        text = fmt.get("text", "").strip()
        if text:
            for part in text.split(","):
                part = part.strip()
                if any(keep in part.lower() for keep in KEEP_TERMS):
                    tags.append(part)
    # Deduplicate
    seen = set()
    result = []
    for tag in tags:
        if tag.lower() not in seen:
            seen.add(tag.lower())
            result.append(tag)
    return result


def find_best_match(results, artist, album, year):
    """
    Find the best matching Discogs result for an album.
    Prefers results that match the year and have meaningful format tags.
    Returns release_id or None if no confident match found.
    """
    if not results:
        return None

    year_str = str(year) if year else ""

    for result in results:
        title = result.get("title", "").lower()
        result_year = str(result.get("year", ""))
        country = result.get("country", "")

        # Title should contain the album name
        album_lower = album.lower()
        if album_lower not in title:
            continue

        # Prefer year match
        if year_str and result_year == year_str:
            return result.get("id")

    # Fall back to first result if title matches
    for result in results:
        title = result.get("title", "").lower()
        if album.lower() in title:
            return result.get("id")

    return None


def run_beet(args):
    """Run a beet command and return stdout, stderr."""
    cmd = ["beet"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, input="yes\n")
    return result.stdout.strip(), result.stderr.strip()


def get_library_albums(artist_filter=None):
    """Get all unique albums from the beets library."""
    fmt = "$albumartist\t$album\t$year\t$albumdisambig"
    if artist_filter:
        stdout, _ = run_beet(["info", "-a", "-f", fmt, "albumartist:{}".format(artist_filter)])
    else:
        stdout, _ = run_beet(["info", "-a", "-f", fmt])

    albums = []
    seen = set()
    for line in stdout.splitlines():
        if not line.strip() or "\t" not in line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        albumartist = parts[0].strip()
        album = parts[1].strip()
        year = parts[2].strip()
        disambig = parts[3].strip() if len(parts) > 3 else ""

        key = "{}||{}".format(albumartist, album)
        if key not in seen:
            seen.add(key)
            albums.append({
                "albumartist": albumartist,
                "album": album,
                "year": year,
                "albumdisambig": disambig,
            })

    return albums


def process_album(album_info, dry_run=False, force=False, move=False):
    """Process a single album - search Discogs and apply tags if found."""
    albumartist = album_info["albumartist"]
    album = album_info["album"]
    year = album_info["year"]
    current_disambig = album_info["albumdisambig"]

    if current_disambig and not force:
        log.info("SKIP {} - {} (already has disambig: {})".format(
            albumartist, album, current_disambig))
        return "skipped"

    log.info("Processing: {} - {}".format(albumartist, album))

    try:
        time.sleep(REQUEST_DELAY)
        results = discogs_search(albumartist, album)

        if not results:
            log.info("  No Discogs results found")
            return "no_match"

        release_id = find_best_match(results, albumartist, album, year)

        if not release_id:
            log.info("  No confident match found in {} results".format(len(results)))
            return "no_match"

        time.sleep(REQUEST_DELAY)
        release = discogs_get_release(release_id)
        tags = extract_format_tags(release)

        if not tags:
            log.info("  Match found (ID: {}) but no meaningful format tags".format(release_id))
            return "no_tags"

        disambig = ", ".join(tags)
        log.info("  Match: Discogs ID {} -> albumdisambig = '{}'".format(release_id, disambig))

        if dry_run:
            log.info("  [DRY RUN] Would set albumdisambig = '{}'".format(disambig))
            return "would_update"

        # Apply to beets at album level
        query = 'albumartist:"{}" album:"{}"'.format(albumartist, album)
        stdout, stderr = run_beet([
            "modify", "--album", "--yes", query,
            "albumdisambig={}".format(disambig)
        ])
        if stderr and "error" in stderr.lower():
            log.warning("  beet modify stderr: {}".format(stderr))

        if move:
            stdout, stderr = run_beet(["move", query])
            log.info("  Moved: {}".format(stdout or "already in place"))

        return "updated"

    except requests.HTTPError as e:
        log.error("  HTTP error: {}".format(e))
        return "error"
    except Exception as e:
        log.error("  Unexpected error: {}".format(e))
        return "error"


def main():
    parser = argparse.ArgumentParser(description="Bulk apply Discogs tags to beets library")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without applying")
    parser.add_argument("--force", action="store_true", help="Re-process albums with existing disambig")
    parser.add_argument("--artist", type=str, help="Only process albums by this artist")
    parser.add_argument("--move", action="store_true", help="Run beet move after updating tags")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("Discogs Bulk Tagger started at {}".format(datetime.now()))
    log.info("dry_run={} force={} artist={} move={}".format(
        args.dry_run, args.force, args.artist, args.move))
    log.info("=" * 60)

    albums = get_library_albums(artist_filter=args.artist)
    log.info("Found {} unique albums to process".format(len(albums)))

    stats = {"updated": 0, "skipped": 0, "no_match": 0, "no_tags": 0,
             "would_update": 0, "error": 0}

    for i, album_info in enumerate(albums, 1):
        log.info("[{}/{}]".format(i, len(albums)))
        result = process_album(
            album_info,
            dry_run=args.dry_run,
            force=args.force,
            move=args.move,
        )
        stats[result] = stats.get(result, 0) + 1

    log.info("=" * 60)
    log.info("Done. Results:")
    for k, v in stats.items():
        log.info("  {}: {}".format(k, v))
    log.info("=" * 60)


if __name__ == "__main__":
    main()