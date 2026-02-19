#!/usr/bin/env python3
"""
discogs_bulk_tag.py - Bulk apply Discogs format descriptions to beets library

Searches Discogs for each album in your beets library and applies:
- meaningful format tags (Remastered, Deluxe Edition, etc.) to albumdisambig
- primary artist name to albumartist_primary custom field (does NOT overwrite
  albumartist -- the original collaborative name is preserved)

The albumartist_primary field is used in the path template so folders are
organized under the primary artist (e.g. "Gabry Ponte/") rather than the
full collaborative credit ("Gabry Ponte & Avao/"). If Discogs has no match
the field stays empty and the path template falls back to $albumartist.

Usage:
    python3 discogs_bulk_tag.py [--dry-run] [--force] [--artist "Artist Name"]

Options:
    --dry-run     Show what would be changed without applying anything
    --force       Re-process albums that already have albumdisambig set
    --artist X    Only process albums by a specific artist
    --move        Run beet move after updating tags (renames folders)

Examples:
    python3 discogs_bulk_tag.py --dry-run
    python3 discogs_bulk_tag.py --artist "Gabry Ponte"
    python3 discogs_bulk_tag.py --move
"""

import sys
import time
import subprocess
import requests
import argparse
import logging
from datetime import datetime

# Config
DISCOGS_TOKEN = "nSxVRTjzwbgIxzManORnSuDCIUEqouNYUcKymrHv"
DISCOGS_USER_AGENT = "BeetsV7BulkTagger/1.0"
LOG_FILE = "/data/discogs_bulk_tag.log"

REQUEST_DELAY = 2.0  # 2s between requests = safely under Discogs 60 req/min limit

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger(__name__)


def discogs_request(url, headers, params=None, retries=3):
    """Make a Discogs API request with automatic retry on 429 rate limit."""
    for attempt in range(retries):
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code == 429:
            wait = 60  # Discogs rate limit window is 60 seconds
            log.warning(f"  Rate limited (429) -- waiting {wait}s before retry {attempt + 1}/{retries}")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp
    raise requests.HTTPError(f"Failed after {retries} retries due to rate limiting")


def strip_collaborators(artist):
    """
    Strip collaborators from an artist string for Discogs search.
    Discogs indexes releases under the primary artist only, so searching
    for "Gabry Ponte & Datura" finds nothing while "Gabry Ponte" finds it.
    We search with just the primary artist, then validate the result.
    """
    import re
    cleaned = re.sub(
        r'\s*(?:&|and|x|X|feat\.?|ft\.?|featuring|with|vs\.?)\s+.*$',
        '', artist, flags=re.IGNORECASE
    ).strip()
    return cleaned if cleaned else artist


def discogs_search(artist, album):
    # Search using primary artist only -- collaborative names don't match
    search_artist = strip_collaborators(artist)
    url = "https://api.discogs.com/database/search"
    headers = {
        "Authorization": "Discogs token={}".format(DISCOGS_TOKEN),
        "User-Agent": DISCOGS_USER_AGENT,
    }
    params = {
        "artist": search_artist,
        "release_title": album,
        "type": "release",
        "per_page": 5,
    }
    resp = discogs_request(url, headers, params=params)
    return resp.json().get("results", [])


def discogs_get_release(release_id):
    url = "https://api.discogs.com/releases/{}".format(release_id)
    headers = {
        "Authorization": "Discogs token={}".format(DISCOGS_TOKEN),
        "User-Agent": DISCOGS_USER_AGENT,
    }
    resp = discogs_request(url, headers)
    return resp.json()


def extract_format_tags(release):
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
    seen = set()
    result = []
    for tag in tags:
        if tag.lower() not in seen:
            seen.add(tag.lower())
            result.append(tag)
    return result


def extract_primary_artist(release):
    """
    Extract the primary artist name from a Discogs release.

    Discogs stores artists as an array where the first entry is the primary
    artist. For collaborative releases like "Gabry Ponte & Avao", the
    artists array has two entries -- we take just the first one.

    The 'anv' field (artist name variation) is the display name used on
    the release. We prefer anv over name if it's set, as it matches what
    the artist is actually credited as on that release.

    Returns the primary artist string or None if not available.
    """
    artists = release.get("artists", [])
    if not artists:
        return None

    primary = artists[0]
    # Prefer anv (artist name variation) if set, otherwise use name
    name = primary.get("anv") or primary.get("name") or ""
    # Discogs appends a number to disambiguate artists with the same name
    # e.g. "Prince (2)" -- strip the trailing number in parentheses
    import re
    name = re.sub(r'\s*\(\d+\)\s*$', '', name).strip()
    return name if name else None


def find_best_match(results, artist, album, year):
    if not results:
        return None

    year_str = str(year) if year else ""

    for result in results:
        title = result.get("title", "").lower()
        result_year = str(result.get("year", ""))
        if album.lower() not in title:
            continue
        if year_str and result_year == year_str:
            return result.get("id")

    for result in results:
        title = result.get("title", "").lower()
        if album.lower() in title:
            return result.get("id")

    return None


def run_beet(args):
    cmd = ["beet"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, input="yes\n")
    return result.stdout.strip(), result.stderr.strip()


def get_library_albums(artist_filter=None):
    fmt = "$albumartist\t$album\t$year\t$albumdisambig\t$albumartist_primary"
    if artist_filter:
        stdout, _ = run_beet(["info", "-a", "-f", fmt,
                               "albumartist:{}".format(artist_filter)])
    else:
        stdout, _ = run_beet(["info", "-a", "-f", fmt, "albumartist::."]) 

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
        primary = parts[4].strip() if len(parts) > 4 else ""

        key = "{}||{}".format(albumartist, album)
        if key not in seen:
            seen.add(key)
            albums.append({
                "albumartist": albumartist,
                "album": album,
                "year": year,
                "albumdisambig": disambig,
                "albumartist_primary": primary,
            })

    return albums


def process_album(album_info, dry_run=False, force=False, move=False):
    albumartist = album_info["albumartist"]
    album = album_info["album"]
    year = album_info["year"]
    current_disambig = album_info["albumdisambig"]
    current_primary = album_info["albumartist_primary"]

    # Skip if both disambig and primary artist are already set (unless forced)
    if current_disambig and current_primary and not force:
        log.info("SKIP {} - {} (already processed)".format(albumartist, album))
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

        # Extract primary artist
        primary_artist = extract_primary_artist(release)

        # Extract format tags
        tags = extract_format_tags(release)
        disambig = ", ".join(tags) if tags else current_disambig

        log.info("  Discogs ID: {}".format(release_id))
        if primary_artist and primary_artist != albumartist:
            log.info("  Primary artist: '{}' -> albumartist_primary = '{}'".format(
                albumartist, primary_artist))
        if tags:
            log.info("  Format tags: {}".format(disambig))

        if dry_run:
            if primary_artist:
                log.info("  [DRY RUN] Would set albumartist_primary = '{}'".format(primary_artist))
            if tags:
                log.info("  [DRY RUN] Would set albumdisambig = '{}'".format(disambig))
            return "would_update"

        query = 'albumartist:"{}" album:"{}"'.format(albumartist, album)
        modified = False

        # Write primary artist to custom field (never overwrites albumartist)
        if primary_artist and primary_artist != current_primary:
            stdout, stderr = run_beet([
                "modify", "--album", "--yes", query,
                "albumartist_primary={}".format(primary_artist)
            ])
            if stderr and "error" in stderr.lower():
                log.warning("  albumartist_primary modify error: {}".format(stderr))
            else:
                log.info("  Set albumartist_primary = '{}'".format(primary_artist))
                modified = True

        # Write disambig if we found format tags
        if tags and disambig != current_disambig:
            stdout, stderr = run_beet([
                "modify", "--album", "--yes", query,
                "albumdisambig={}".format(disambig)
            ])
            if stderr and "error" in stderr.lower():
                log.warning("  albumdisambig modify error: {}".format(stderr))
            else:
                log.info("  Set albumdisambig = '{}'".format(disambig))
                modified = True

        if move and modified:
            stdout, stderr = run_beet(["move", query])
            log.info("  Moved: {}".format(stdout or "already in place"))

        return "updated" if modified else "no_change"

    except requests.HTTPError as e:
        log.error("  HTTP error: {}".format(e))
        return "error"
    except Exception as e:
        log.error("  Unexpected error: {}".format(e))
        return "error"


def main():
    parser = argparse.ArgumentParser(
        description="Bulk apply Discogs tags to beets library")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show changes without applying")
    parser.add_argument("--force", action="store_true",
                        help="Re-process albums with existing disambig/primary")
    parser.add_argument("--artist", type=str,
                        help="Only process albums by this artist")
    parser.add_argument("--move", action="store_true",
                        help="Run beet move after updating tags")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("Discogs Bulk Tagger started at {}".format(datetime.now()))
    log.info("dry_run={} force={} artist={} move={}".format(
        args.dry_run, args.force, args.artist, args.move))
    log.info("=" * 60)

    albums = get_library_albums(artist_filter=args.artist)
    log.info("Found {} unique albums to process".format(len(albums)))

    stats = {"updated": 0, "skipped": 0, "no_match": 0, "no_tags": 0,
             "would_update": 0, "no_change": 0, "error": 0}

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
        if v > 0:
            log.info("  {}: {}".format(k, v))
    log.info("=" * 60)


if __name__ == "__main__":
    main()