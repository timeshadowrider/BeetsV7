#!/usr/bin/env python3
"""
discogs_tag.py - Apply Discogs format descriptions directly into beets album name

Usage:
    python3 discogs_tag.py <discogs_release_id> <beets_query>

Examples:
    python3 discogs_tag.py 1831542 "album:Hotel California"
"""

import sys
import subprocess
import requests
import json

DISCOGS_TOKEN = "nSxVRTjzwbgIxzManORnSuDCIUEqouNYUcKymrHv"
DISCOGS_USER_AGENT = "BeetsV7Tagger/1.0"

# Only these terms will be appended to the album name
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


def get_discogs_release(release_id):
    url = "https://api.discogs.com/releases/{}".format(release_id)
    headers = {
        "Authorization": "Discogs token={}".format(DISCOGS_TOKEN),
        "User-Agent": DISCOGS_USER_AGENT,
    }
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
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


def run_beet(args):
    result = subprocess.run(["beet"] + args, capture_output=True, text=True, input="yes\n")
    return result.stdout.strip(), result.stderr.strip()


def get_current_album_name(beets_query):
    stdout, _ = run_beet(["info", "-f", "$album", beets_query])
    # All tracks should have same album name, just take first line
    lines = [l.strip() for l in stdout.splitlines() if l.strip()]
    return lines[0] if lines else None


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 discogs_tag.py <discogs_release_id> <beets_query>")
        print('Example: python3 discogs_tag.py 1831542 "album:Hotel California"')
        sys.exit(1)

    release_id = sys.argv[1]
    beets_query = " ".join(sys.argv[2:])

    print("-> Fetching Discogs release {}...".format(release_id))
    try:
        release = get_discogs_release(release_id)
    except requests.HTTPError as e:
        print("Error fetching release: {}".format(e))
        sys.exit(1)

    artist = release.get("artists_sort", "Unknown Artist")
    title = release.get("title", "Unknown Album")
    year = release.get("year", "")
    formats = release.get("formats", [])

    print("\nRelease: {} - {} ({})".format(artist, title, year))
    print("Raw formats: {}".format(json.dumps(formats, indent=2)))

    tags = extract_format_tags(release)

    if not tags:
        print("\nNo meaningful format tags found. Nothing to do.")
        sys.exit(0)

    disambig = ", ".join(tags)
    print("\nExtracted tags: {}".format(tags))

    # Get current album name from beets
    current_album = get_current_album_name(beets_query)
    if not current_album:
        print("Could not find album in beets library for query: {}".format(beets_query))
        sys.exit(1)

    # Strip any existing bracket suffix before adding new one
    import re
    base_album = re.sub(r'\s*\[.*?\]\s*$', '', current_album).strip()
    new_album = "{} [{}]".format(base_album, disambig)

    print("\nCurrent album name : {}".format(current_album))
    print("New album name     : {}".format(new_album))

    confirm = input("\nApply to beets? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        sys.exit(0)

    # Set both album name and albumdisambig
    print("\n-> Updating album name...")
    stdout, stderr = run_beet(["modify", "--album", "--yes", beets_query,
                                "album={}".format(new_album),
                                "albumdisambig={}".format(disambig)])
    if stdout:
        print(stdout)
    if stderr and "already in place" not in stderr:
        print("  [stderr] {}".format(stderr))

    print("\n-> Moving files to new path...")
    stdout, stderr = run_beet(["move", beets_query])
    if stdout:
        print(stdout)
    if stderr:
        print("  [stderr] {}".format(stderr))

    print("\nDone. Album is now: {}".format(new_album))


if __name__ == "__main__":
    main()