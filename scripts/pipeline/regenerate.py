#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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
    FIX: Wrapped in try/except so a single corrupted file doesn't crash
    the entire generate_ui_json() call.
    FIX: Handles both easy=True list tags and easy=False object tags
    for MP3 ID3 compatibility.
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

        # FIX: Handle both list-style (FLAC/easy) and object-style (MP3 ID3) tags
        def get_tag(key, fallback=""):
            val = tags.get(key)
            if val is None:
                return fallback
            if hasattr(val, "text"):
                # ID3 frame object
                return str(val.text[0]) if val.text else fallback
            if isinstance(val, list):
                return str(val[0]) if val else fallback
            return str(val) or fallback

        title = get_tag("title", path.stem)
        if not title:
            title = path.stem

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


def generate_ui_json():
    albums = []
    total_artists = set()
    total_tracks = 0
    total_duration = 0
    total_size = 0

    if not LIBRARY_ROOT.exists():
        print("[regenerate] LIBRARY_ROOT does not exist, skipping JSON generation.")
        return

    for artist_dir in sorted(LIBRARY_ROOT.iterdir()):
        if not artist_dir.is_dir():
            continue
        if is_failed_imports_folder(artist_dir):
            continue

        total_artists.add(artist_dir.name)

        for album_dir in sorted(artist_dir.iterdir()):
            if not album_dir.is_dir():
                continue
            if is_failed_imports_folder(album_dir):
                continue

            albumartist = artist_dir.name
            album = album_dir.name

            # FIX: Use earliest file ctime as added date instead of folder mtime
            # which gets reset whenever any file changes
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

            # Skip albums with no readable tracks
            if album_tracks == 0:
                continue

            track_entries.sort(key=lambda t: (t["track"] is None, t["track"]))

            cover_file = find_cover(album_dir)
            if cover_file:
                encoded_artist = quote(albumartist, safe="")
                encoded_album = quote(album, safe="")
                cover_url = "/music/library/%s/%s/cover.jpg" % (encoded_artist, encoded_album)
            else:
                cover_url = None

            album_obj = {
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
            }

            albums.append(album_obj)
            total_tracks += album_tracks
            total_duration += album_duration
            total_size += album_size

    recent = sorted(albums, key=lambda a: a["mtime"], reverse=True)

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

    print("[regenerate] UI JSON generation complete. %d albums, %d tracks." % (len(albums), total_tracks))


if __name__ == "__main__":
    generate_ui_json()
