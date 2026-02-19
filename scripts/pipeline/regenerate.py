#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Incremental UI JSON regenerator.

On each run:
  1. Load existing albums.json to build a cache of {album_path: mtime}
  2. Walk LIBRARY_ROOT - only rescan folders whose mtime has changed or are new
  3. Remove entries for folders that no longer exist
  4. Write updated albums.json, recent_albums.json, stats.json

This means a full 3000-track library rescan only happens once (or after a
full wipe of albums.json). Subsequent runs only touch changed folders and
complete in seconds.
"""

import os
import json
from pathlib import Path
from datetime import datetime
from urllib.parse import quote
from mutagen import File as MutagenFile

DATA_DIR = Path("/data")
LIBRARY_ROOT = Path("/music/library")
FAILED_IMPORTS_NAME = "failed_imports"


def human_time(seconds: float) -> str:
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return "%02d:%02d:%02d" % (h, m, s)
    return "%02d:%02d" % (m, s)


def extract_track_metadata(path: Path):
    """
    Extract audio metadata via Mutagen.
    Returns None on any failure so a single bad file can't crash the run.
    """
    try:
        audio = MutagenFile(path)
        if audio is None:
            return None

        duration = getattr(audio.info, "length", 0.0)
        codec = audio.mime[0] if hasattr(audio, "mime") and audio.mime else path.suffix.replace(".", "").upper()
        bit_depth = getattr(audio.info, "bits_per_sample", None)
        sample_rate = getattr(audio.info, "sample_rate", None)
        size = path.stat().st_size

        tags = audio.tags or {}

        def get_tag(key, fallback=""):
            val = tags.get(key)
            if val is None:
                return fallback
            if hasattr(val, "text"):
                return str(val.text[0]) if val.text else fallback
            if isinstance(val, list):
                return str(val[0]) if val else fallback
            return str(val) or fallback

        title = get_tag("title", path.stem) or path.stem

        track = None
        track_raw = get_tag("tracknumber", "")
        if track_raw:
            try:
                track = int(str(track_raw).split("/")[0])
            except (ValueError, AttributeError):
                track = None

        return {
            "track": track,
            "title": title,
            "duration": duration,
            "duration_human": human_time(duration),
            "bit_depth": bit_depth,
            "sample_rate": sample_rate,
            "codec": codec,
            "size": size,
            "path": str(path),
        }

    except Exception as e:
        print("[regenerate] WARNING: could not read %s: %s" % (path, e))
        return None


def find_cover(album_dir: Path):
    for name in ("cover.jpg", "cover.png", "Cover.jpg", "Cover.png", "folder.jpg", "folder.png"):
        p = album_dir / name
        if p.exists():
            return p
    return None


def is_failed_imports_folder(path: Path) -> bool:
    return FAILED_IMPORTS_NAME in [p.name for p in path.parents] or path.name == FAILED_IMPORTS_NAME


def scan_album_dir(artist_dir: Path, album_dir: Path):
    """
    Scan a single album directory and return an album object, or None if
    no valid audio files are found.
    """
    albumartist = artist_dir.name
    album = album_dir.name

    try:
        mtime = album_dir.stat().st_mtime
    except Exception:
        mtime = 0
    added_iso = datetime.fromtimestamp(mtime).isoformat() if mtime else ""

    track_entries = []
    album_duration = 0.0
    album_size = 0
    album_tracks = 0

    for root, dirs, files in os.walk(album_dir):
        if FAILED_IMPORTS_NAME in root.split(os.sep):
            continue
        for f in sorted(files):
            p = Path(root) / f
            if p.suffix.lower() not in {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aac"}:
                continue
            meta = extract_track_metadata(p)
            if meta:
                track_entries.append(meta)
                album_duration += meta["duration"]
                album_size += meta["size"]
                album_tracks += 1

    if album_tracks == 0:
        return None

    track_entries.sort(key=lambda t: (t["track"] is None, t["track"]))

    cover_file = find_cover(album_dir)
    if cover_file:
        encoded_artist = quote(albumartist, safe="")
        encoded_album = quote(album, safe="")
        cover_url = "/music/library/%s/%s/cover.jpg" % (encoded_artist, encoded_album)
    else:
        cover_url = None

    return {
        "albumartist": albumartist,
        "album": album,
        "cover": cover_url,
        "mtime": mtime,
        "added": added_iso,
        "total_duration": album_duration,
        "total_duration_human": human_time(album_duration),
        "total_tracks": album_tracks,
        "total_size": album_size,
        "tracks": track_entries,
        "_path": str(album_dir),  # used as cache key
    }


def load_existing_cache() -> dict:
    """
    Load existing albums.json and return a dict keyed by album filesystem path.
    Returns empty dict if file doesn't exist, is malformed, or entries lack _path.
    """
    albums_path = DATA_DIR / "albums.json"
    if not albums_path.exists():
        return {}
    try:
        data = json.loads(albums_path.read_text(encoding="utf-8"))
        cache = {a["_path"]: a for a in data if "_path" in a}
        if not cache and data:
            # Old format without _path — force full rescan this one time
            print("[regenerate] Old albums.json format detected (no _path) — doing full rescan to upgrade")
        return cache
    except Exception as e:
        print("[regenerate] Could not load existing albums.json: %s — doing full scan" % e)
        return {}


def generate_ui_json():
    """
    Incremental UI JSON generation.

    Only rescans album folders whose mtime has changed since the last run.
    Unchanged folders are reused from the existing albums.json cache.
    Folders that no longer exist are dropped automatically.
    """
    if not LIBRARY_ROOT.exists():
        print("[regenerate] LIBRARY_ROOT %s does not exist, skipping." % LIBRARY_ROOT)
        return

    cache = load_existing_cache()
    seen_paths = set()
    albums = []
    scanned = 0
    reused = 0

    for artist_dir in sorted(LIBRARY_ROOT.iterdir()):
        if not artist_dir.is_dir():
            continue
        if is_failed_imports_folder(artist_dir):
            continue

        for album_dir in sorted(artist_dir.iterdir()):
            if not album_dir.is_dir():
                continue
            if is_failed_imports_folder(album_dir):
                continue

            album_path = str(album_dir)
            seen_paths.add(album_path)

            try:
                current_mtime = album_dir.stat().st_mtime
            except Exception:
                current_mtime = 0

            cached = cache.get(album_path)

            # Reuse cached entry if mtime is unchanged (within 1 second)
            if cached and abs(cached.get("mtime", 0) - current_mtime) < 1.0:
                albums.append(cached)
                reused += 1
                continue

            # New or changed folder — rescan
            album_obj = scan_album_dir(artist_dir, album_dir)
            if album_obj:
                albums.append(album_obj)
                scanned += 1
            else:
                print("[regenerate] Skipping (no audio): %s" % album_dir)

    dropped = len([k for k in cache if k not in seen_paths])

    print("[regenerate] Scanned: %d new/changed | Reused: %d cached | Dropped: %d deleted"
          % (scanned, reused, dropped))

    recent = sorted(albums, key=lambda a: a["mtime"], reverse=True)

    total_tracks = sum(a.get("total_tracks", 0) for a in albums)
    total_duration = sum(a.get("total_duration", 0.0) for a in albums)
    total_size = sum(a.get("total_size", 0) for a in albums)
    total_artists = {a["albumartist"] for a in albums if a.get("albumartist")}

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with open(DATA_DIR / "albums.json", "w", encoding="utf-8") as f:
        json.dump(albums, f, indent=2)

    with open(DATA_DIR / "recent_albums.json", "w", encoding="utf-8") as f:
        json.dump(recent, f, indent=2)

    stats = {
        "artists": len(total_artists),
        "albums": len(albums),
        "tracks": total_tracks,
        "total_duration": total_duration,
        "total_duration_human": human_time(total_duration),
        "total_size": total_size,
    }

    with open(DATA_DIR / "stats.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    print("[regenerate] Complete: %d albums, %d tracks, %d artists."
          % (len(albums), total_tracks, len(total_artists)))


if __name__ == "__main__":
    generate_ui_json()
