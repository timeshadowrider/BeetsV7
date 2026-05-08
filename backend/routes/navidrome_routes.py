"""
Navidrome M3U playlist builder
POST /ui/navidrome/playlist/upload  — match CSV, write .m3u to playlist dir
GET  /ui/navidrome/playlist/download/{name} — stream the .m3u back to browser
GET  /ui/logs/navidrome  — tail the navidrome build log (for live polling)
DELETE /ui/logs/navidrome — clear the log

Required env vars (add to .env):
  NAVIDROME_PLAYLIST_DIR  — host path the backend can write M3U files to.
                            Must be the same directory Navidrome watches.
                            e.g. /srv/mergerfs/SnapRaid_mergerfs/Beets-Flask/clean/playlists

  NAVIDROME_MUSIC_PREFIX  — the path prefix Navidrome uses for your music root
                            inside its own container.  Default: /music
                            Beets paths are assumed to start with /music/library/;
                            that prefix gets replaced with NAVIDROME_MUSIC_PREFIX.

Example path rewrite:
  beets returns  → /music/library/Weezer/Pinkerton/01 Tired of Sex.flac
  M3U entry      → /music/Weezer/Pinkerton/01 Tired of Sex.flac
  (matches ND_MUSICFOLDER=/music inside Navidrome's container)
"""

import csv
import io
import logging
import os
import re as _re
from pathlib import Path
from typing import Optional

from backend.utils.beet_search import search_beets_for_track as _beet_search_impl

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PLAYLIST_DIR = os.getenv(
    "NAVIDROME_PLAYLIST_DIR",
    "/srv/mergerfs/SnapRaid_mergerfs/Beets-Flask/clean/playlists",
)
# What Navidrome calls its music root inside *its* container (ND_MUSICFOLDER).
NAVIDROME_MUSIC_PREFIX = os.getenv("NAVIDROME_MUSIC_PREFIX", "/music")

# Beets absolute path prefix — everything after this becomes the relative path
# under NAVIDROME_MUSIC_PREFIX.
_BEETS_LIBRARY_PREFIX = "/music/library/"

LOG_PATH = Path("/data/navidrome_playlist.log")

# ---------------------------------------------------------------------------
# Logger — mirrors the volumio logger pattern so the frontend can poll it
# ---------------------------------------------------------------------------

navidrome_logger = logging.getLogger("navidrome")
navidrome_logger.setLevel(logging.DEBUG)
if not navidrome_logger.handlers:
    _fh = logging.FileHandler(str(LOG_PATH))
    _fh.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", "%H:%M:%S"))
    navidrome_logger.addHandler(_fh)

router = APIRouter(tags=["navidrome"])

# ---------------------------------------------------------------------------
# Log endpoints (consumed by the frontend live-log poller)
# ---------------------------------------------------------------------------

@router.get("/logs", response_class=PlainTextResponse, tags=["navidrome"])
def get_navidrome_log():
    if not LOG_PATH.exists():
        return ""
    return LOG_PATH.read_text(encoding="utf-8")


@router.delete("/logs", tags=["navidrome"])
def clear_navidrome_log():
    if LOG_PATH.exists():
        LOG_PATH.write_text("", encoding="utf-8")
    return {"status": "cleared"}


# ---------------------------------------------------------------------------
# Matching helpers — delegate to shared beet_search utility
# ---------------------------------------------------------------------------

def _search_beets_for_track(title: str, artist: str) -> str | None:
    return _beet_search_impl(
        title, artist,
        library_prefix=_BEETS_LIBRARY_PREFIX,
        logger=navidrome_logger,
    )


# ---------------------------------------------------------------------------
# Path rewrite
# Converts a beets absolute path → the path Navidrome will see in the M3U.
#
# Beets:      /music/library/Weezer/Pinkerton/01 Tired of Sex.flac
# Navidrome:  /music/Weezer/Pinkerton/01 Tired of Sex.flac
#             ^^^^^^
#             NAVIDROME_MUSIC_PREFIX (matches ND_MUSICFOLDER in docker-compose)
# ---------------------------------------------------------------------------

def _path_to_navidrome(abs_path: str) -> str:
    if abs_path.startswith(_BEETS_LIBRARY_PREFIX):
        relative = abs_path[len(_BEETS_LIBRARY_PREFIX):]
        return NAVIDROME_MUSIC_PREFIX.rstrip("/") + "/" + relative
    # Fallback: return as-is; Navidrome may still resolve it if the mount
    # paths happen to align.
    navidrome_logger.warning(
        f"[NAVIDROME] Path did not start with {_BEETS_LIBRARY_PREFIX!r}, "
        f"using raw path: {abs_path}"
    )
    return abs_path


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/playlist/upload")
async def build_navidrome_playlist(
    file: UploadFile = File(...),
    playlist_name: Optional[str] = Form(None),
):
    # Clear previous log for this session
    LOG_PATH.write_text("", encoding="utf-8")
    navidrome_logger.info(f"[NAVIDROME] === New build: {file.filename} ===")

    contents = await file.read()
    try:
        text = contents.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    except Exception as e:
        raise HTTPException(400, f"Could not parse CSV: {e}")

    if not rows:
        raise HTTPException(400, "CSV file is empty")

    # Column detection — same logic as Volumio builder
    sample = rows[0]
    cols = list(sample.keys())
    navidrome_logger.info(f"[NAVIDROME] CSV columns: {cols}")

    title_col = (
        next((c for c in cols if "track" in c.lower() and "name" in c.lower()), None)
        or next((c for c in cols if "title" in c.lower()), None)
    )
    artist_col = next((c for c in cols if "artist" in c.lower()), None)
    album_col  = next((c for c in cols if "album"  in c.lower()), None)

    if not title_col:
        raise HTTPException(400, f"Cannot find track title column. Columns: {cols}")

    navidrome_logger.info(
        f"[NAVIDROME] Columns → title='{title_col}' "
        f"artist='{artist_col}' album='{album_col}'"
    )
    navidrome_logger.info(f"[NAVIDROME] {len(rows)} tracks to process...")

    # Playlist name: prefer form field, fall back to CSV filename
    raw_name = (playlist_name or file.filename).replace(".csv", "")
    raw_name = raw_name.replace("_", " ").replace("-", " ").strip()
    safe_name = _re.sub(r"[^\w\s\-]", "", raw_name).strip()
    safe_name = _re.sub(r"\s+", "_", safe_name) or "playlist"

    matched_paths: list[str] = []
    unmatched: list[str] = []

    for row in rows:
        title  = row.get(title_col,  "").strip()
        artist = row.get(artist_col, "").strip() if artist_col else ""
        if not title:
            continue

        abs_path = _search_beets_for_track(title, artist)
        if abs_path:
            matched_paths.append(_path_to_navidrome(abs_path))
        else:
            unmatched.append(f"{artist} - {title}" if artist else title)

    navidrome_logger.info(
        f"[NAVIDROME] Search complete: "
        f"{len(matched_paths)} matched, {len(unmatched)} unmatched"
    )

    if not matched_paths:
        return {
            "status": "no_matches",
            "playlist": safe_name,
            "matched": 0,
            "total": len(rows),
            "unmatched_count": len(unmatched),
            "unmatched": unmatched[:20],
            "message": "No tracks from the CSV were found in your Beets library.",
        }

    # Write M3U
    try:
        os.makedirs(PLAYLIST_DIR, exist_ok=True)
    except OSError as e:
        raise HTTPException(
            500,
            f"Cannot create playlist directory '{PLAYLIST_DIR}': {e}. "
            "Check NAVIDROME_PLAYLIST_DIR and that the backend has write access.",
        )

    output_path = os.path.join(PLAYLIST_DIR, f"{safe_name}.m3u")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for p in matched_paths:
            f.write(p + "\n")

    navidrome_logger.info(
        f"[NAVIDROME] Wrote {len(matched_paths)} tracks → {output_path}"
    )
    navidrome_logger.info(
        f"[NAVIDROME] === Done: {len(matched_paths)}/{len(rows)} matched ==="
    )

    return {
        "status": "ok",
        "playlist": safe_name,
        "matched": len(matched_paths),
        "unmatched_count": len(unmatched),
        "total": len(rows),
        "unmatched": unmatched[:20],
        "output_path": output_path,
    }


@router.get("/playlist/download/{name}")
async def download_navidrome_playlist(name: str):
    """Stream the saved M3U back to the browser."""
    safe_name = _re.sub(r"[^\w\s\-]", "", name).strip()
    safe_name = _re.sub(r"\s+", "_", safe_name)
    path = os.path.join(PLAYLIST_DIR, f"{safe_name}.m3u")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Playlist not found")
    return FileResponse(path, media_type="audio/x-mpegurl", filename=f"{safe_name}.m3u")
