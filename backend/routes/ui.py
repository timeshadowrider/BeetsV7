# backend/routes/ui.py
from fastapi import APIRouter, HTTPException, UploadFile, File, Request
from fastapi.responses import PlainTextResponse, FileResponse
from pathlib import Path
import subprocess
import threading
import logging
import asyncio
import json
import os
import io
import csv
import unicodedata
from urllib.parse import unquote

DATA_DIR = Path("/data")
MUSIC_DIR = Path("/music/library")
LOG_PIPELINE = DATA_DIR / "pipeline_verbose.log"
LOG_BEETS = DATA_DIR / "last_beets_imports.log"
LOG_VOLUMIO = DATA_DIR / "volumio_playlist.log"

VOLUMIO_HOST = os.getenv("VOLUMIO_HOST", "http://10.0.0.102:3000")
SLSKD_HOST   = os.getenv("SLSKD_HOST",   "http://10.0.0.100:5030")
SLSKD_API_KEY = os.getenv("SLSKD_API_KEY", "")
SLSKD_HEADERS = {"X-API-Key": SLSKD_API_KEY}

# ---------------------------------------------------------
# Volumio-specific file logger
# ---------------------------------------------------------
volumio_logger = logging.getLogger("volumio")
volumio_logger.setLevel(logging.DEBUG)
if not volumio_logger.handlers:
    _vh = logging.FileHandler("/data/volumio_playlist.log")
    _vh.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", "%H:%M:%S"))
    volumio_logger.addHandler(_vh)

# ---------------------------------------------------------
# UI ROUTER (prefix is applied in app.py)
# ---------------------------------------------------------
router = APIRouter(tags=["ui"])


# ---------------------------------------------------------
# Run pipeline (UI-triggered)
# ---------------------------------------------------------
def _run_pipeline():
    subprocess.run(["python3", "/app/scripts/pipeline_controller_v7.py"], check=False)


@router.post("/pipeline/run")
def run_pipeline():
    t = threading.Thread(target=_run_pipeline, daemon=True)
    t.start()
    return {"status": "started"}


# ---------------------------------------------------------
# Shared helper: compute live stats from albums.json
# ---------------------------------------------------------
def _compute_library_stats(data: list) -> dict:
    total_tracks = sum(len(a.get("tracks", [])) for a in data)
    artists = {a.get("albumartist") for a in data if a.get("albumartist")}
    total_size = sum(t.get("filesize", 0) for a in data for t in a.get("tracks", []))
    total_duration = sum(t.get("length", 0) for a in data for t in a.get("tracks", []))
    h = int(total_duration // 3600)
    m = int((total_duration % 3600) // 60)
    s = int(total_duration % 60)
    return {
        "artists": len(artists),
        "albums": len(data),
        "tracks": total_tracks,
        "total_duration": total_duration,
        "total_duration_human": f"{h}:{m:02d}:{s:02d}",
        "total_size": total_size,
    }


def _load_albums() -> list:
    albums_path = DATA_DIR / "albums.json"
    if not albums_path.exists():
        raise HTTPException(404, "albums.json not found")
    return json.loads(albums_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------
# Library Stats
# ---------------------------------------------------------
@router.get("/stats/library")
def get_library_stats():
    albums_path = DATA_DIR / "albums.json"
    if albums_path.exists():
        data = json.loads(albums_path.read_text(encoding="utf-8"))
        return _compute_library_stats(data)
    stats_path = DATA_DIR / "stats.json"
    if stats_path.exists():
        return json.loads(stats_path.read_text(encoding="utf-8"))
    raise HTTPException(404, "No stats available")


# ---------------------------------------------------------
# Inbox Stats
# ---------------------------------------------------------
@router.get("/stats/inbox")
def get_inbox_stats():
    inbox = Path("/inbox")
    artists = 0
    tracks = 0
    for artist_dir in inbox.iterdir():
        if not artist_dir.is_dir() or artist_dir.name == "failed_imports":
            continue
        artists += 1
        for root, dirs, files in os.walk(artist_dir):
            for f in files:
                if Path(f).suffix.lower() in {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aac"}:
                    tracks += 1
    return {"artists": artists, "tracks": tracks}


# ---------------------------------------------------------
# Full Library Analytics
# ---------------------------------------------------------
@router.get("/stats")
def get_global_stats():
    data = _load_albums()
    formats = {}
    bit_depths = {}
    sample_rates = {}
    genres = {}
    years = {}
    total_tracks = 0
    artists = set()
    for album in data:
        aa = album.get("albumartist")
        if aa:
            artists.add(aa)
        total_tracks += len(album.get("tracks", []))
        for t in album.get("tracks", []):
            codec = (t.get("codec") or "").lower()
            if codec:
                formats[codec] = formats.get(codec, 0) + 1
            bd = t.get("bit_depth")
            if bd:
                bit_depths[str(bd)] = bit_depths.get(str(bd), 0) + 1
            sr = t.get("sample_rate")
            if sr:
                sample_rates[str(sr)] = sample_rates.get(str(sr), 0) + 1
            g = t.get("genre")
            if g:
                genres[g] = genres.get(g, 0) + 1
            y = t.get("year")
            if y:
                years[str(y)] = years.get(str(y), 0) + 1
    return {
        "library": {"albums": len(data), "tracks": total_tracks, "artists": len(artists), "album_artists": len(artists)},
        "formats": formats,
        "bit_depths": bit_depths,
        "sample_rates": sample_rates,
        "genres": genres,
        "years": years,
    }


# ---------------------------------------------------------
# Recent Albums
# ---------------------------------------------------------
@router.get("/albums/recent")
def get_recent_albums():
    path = DATA_DIR / "recent_albums.json"
    if not path.exists():
        raise HTTPException(404, "recent_albums.json not found")
    data = json.loads(path.read_text(encoding="utf-8"))
    return sorted(data, key=lambda a: a.get("added", a.get("mtime", "")), reverse=True)


# ---------------------------------------------------------
# All Albums
# ---------------------------------------------------------
@router.get("/albums/all")
def get_all_albums():
    path = DATA_DIR / "albums.json"
    if not path.exists():
        raise HTTPException(404, "albums.json not found")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------
# Cover Art
# ---------------------------------------------------------
@router.get("/library/cover/{artist}/{album}")
def get_cover(artist: str, album: str):
    artist = unquote(artist)
    album = unquote(album)
    cover_path = MUSIC_DIR / artist / album / "cover.jpg"
    if not cover_path.exists():
        raise HTTPException(404, "Cover not found")
    return FileResponse(str(cover_path), media_type="image/jpeg")


# ---------------------------------------------------------
# Logs
# ---------------------------------------------------------
@router.get("/logs/pipeline", response_class=PlainTextResponse)
def get_pipeline_log():
    if not LOG_PIPELINE.exists():
        raise HTTPException(404, "pipeline log not found")
    return LOG_PIPELINE.read_text(encoding="utf-8")


@router.get("/logs/beets", response_class=PlainTextResponse)
def get_beets_log():
    if not LOG_BEETS.exists():
        raise HTTPException(404, "beets log not found")
    return LOG_BEETS.read_text(encoding="utf-8")


@router.get("/logs/volumio", response_class=PlainTextResponse)
def get_volumio_log():
    if not LOG_VOLUMIO.exists():
        return ""
    return LOG_VOLUMIO.read_text(encoding="utf-8")


@router.delete("/logs/volumio")
def clear_volumio_log():
    if LOG_VOLUMIO.exists():
        LOG_VOLUMIO.write_text("", encoding="utf-8")
    return {"status": "cleared"}


# =============================================================
# Volumio Playlist Builder (Spotify CSV -> Volumio WebSocket)
# =============================================================

import re as _re


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = _re.sub(r"[^a-z0-9 ]", "", s.lower())
    return s.strip()


def _primary_artist(artist: str) -> str:
    return artist.replace(";", ",").split(",")[0].strip()


def _beet_query(title: str, artist: str = "") -> str | None:
    norm_title = _normalize(title)
    if artist:
        norm_artist = _normalize(artist)
        cmd = f'beet ls -p title:"{norm_title}" artist:"{norm_artist}"'
    else:
        cmd = f'beet ls -p title:"{norm_title}"'
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        return lines[0] if lines else None
    except Exception as e:
        volumio_logger.error(f"[VOLUMIO] beet query error ({cmd!r}): {e}")
        return None


def _artist_matches(beets_path: str, expected_artist: str) -> bool:
    if not expected_artist:
        return True
    parts = beets_path.replace("/music/library/", "").split("/")
    path_artist = parts[0] if parts else ""
    norm_path = _normalize(path_artist)
    if not norm_path:
        volumio_logger.warning(f"[VOLUMIO] Could not extract artist from path: {beets_path}")
        return False
    all_artists = [a.strip() for a in expected_artist.replace(";", ",").split(",") if a.strip()]
    for candidate in all_artists:
        norm_candidate = _normalize(candidate)
        if norm_candidate in norm_path or norm_path in norm_candidate:
            volumio_logger.info(
                f"[VOLUMIO] Artist verified: path='{path_artist}' matches candidate='{candidate}'"
            )
            return True
    volumio_logger.warning(
        f"[VOLUMIO] Artist mismatch: path='{path_artist}' not in {all_artists} for {beets_path}"
    )
    return False


def _search_beets_for_track(title: str, artist: str) -> str | None:
    volumio_logger.info(f"[VOLUMIO] Searching: '{artist} - {title}'")

    path = _beet_query(title, artist)
    if path:
        volumio_logger.info(f"[VOLUMIO] MATCH pass1 (full artist): {path}")
        return path

    primary = _primary_artist(artist)
    if primary != artist and primary:
        path = _beet_query(title, primary)
        if path:
            volumio_logger.info(f"[VOLUMIO] MATCH pass2 (primary artist): {path}")
            return path

    path = _beet_query(title)
    if path:
        if _artist_matches(path, artist):
            volumio_logger.info(f"[VOLUMIO] MATCH pass3 (title+artist verified): {path}")
            return path
        else:
            volumio_logger.warning(f"[VOLUMIO] REJECTED pass3 (wrong artist): {path}")

    volumio_logger.warning(f"[VOLUMIO] NO MATCH: '{artist} - {title}'")
    return None


def _path_to_volumio_uri(abs_path: str) -> str:
    prefix = "/music/library/"
    if abs_path.startswith(prefix):
        return "mnt/NAS/MUSIC/" + abs_path[len(prefix):]
    return abs_path


async def _push_playlist_via_socket(playlist_name: str, entries: list) -> int:
    import socketio

    sio = socketio.AsyncClient(logger=False, engineio_logger=False)
    errors = 0
    connected = False

    try:
        volumio_logger.info(f"[VOLUMIO] Connecting via WebSocket to {VOLUMIO_HOST}...")
        await sio.connect(VOLUMIO_HOST, transports=["websocket"])
        connected = True
        volumio_logger.info("[VOLUMIO] WebSocket connected")

        await sio.emit("deletePlaylist", {"name": playlist_name})
        await asyncio.sleep(0.5)

        await sio.emit("createPlaylist", {"name": playlist_name})
        await asyncio.sleep(0.5)
        volumio_logger.info(f"[VOLUMIO] Created playlist '{playlist_name}'")

        for entry in entries:
            await sio.emit("addToPlaylist", {
                "name": playlist_name,
                "uri":  entry["uri"],
                "service": entry["service"],
                "title":   entry["title"],
                "artist":  entry["artist"],
                "album":   entry["album"],
            })
            await asyncio.sleep(0.15)
            volumio_logger.info(f"[VOLUMIO] Added: {entry['title']} by {entry['artist']}")

        await asyncio.sleep(1.0)
        volumio_logger.info(f"[VOLUMIO] All {len(entries)} tracks sent via WebSocket")

    except Exception as e:
        volumio_logger.error(f"[VOLUMIO] WebSocket error: {e}")
        errors = len(entries)
    finally:
        if connected:
            await sio.disconnect()

    return errors


@router.post("/volumio/playlist/upload")
async def build_volumio_playlist(file: UploadFile = File(...)):
    LOG_VOLUMIO.write_text("", encoding="utf-8")
    volumio_logger.info(f"[VOLUMIO] === New build: {file.filename} ===")

    contents = await file.read()
    try:
        text = contents.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    except Exception as e:
        raise HTTPException(400, f"Could not parse CSV: {e}")

    if not rows:
        raise HTTPException(400, "CSV file is empty")

    sample = rows[0]
    cols = list(sample.keys())
    volumio_logger.info(f"[VOLUMIO] CSV columns: {cols}")

    title_col = (
        next((c for c in cols if "track" in c.lower() and "name" in c.lower()), None)
        or next((c for c in cols if "title" in c.lower()), None)
    )
    artist_col = next((c for c in cols if "artist" in c.lower()), None)
    album_col  = next((c for c in cols if "album" in c.lower()), None)

    if not title_col:
        raise HTTPException(400, f"Cannot find track title column. Columns: {cols}")

    volumio_logger.info(f"[VOLUMIO] Columns: title='{title_col}' artist='{artist_col}' album='{album_col}'")
    volumio_logger.info(f"[VOLUMIO] {len(rows)} tracks to process...")

    playlist_name = file.filename.replace(".csv", "").replace("_", " ")
    playlist_entries = []
    unmatched = []

    for row in rows:
        title  = row.get(title_col, "").strip()
        artist = row.get(artist_col, "").strip() if artist_col else ""
        album  = row.get(album_col,  "").strip() if album_col  else ""
        if not title:
            continue
        abs_path = _search_beets_for_track(title, artist)
        if abs_path:
            playlist_entries.append({
                "service": "mpd",
                "uri":     _path_to_volumio_uri(abs_path),
                "title":   title,
                "artist":  artist,
                "album":   album,
            })
        else:
            unmatched.append(f"{artist} - {title}" if artist else title)

    volumio_logger.info(f"[VOLUMIO] Search complete: {len(playlist_entries)} matched, {len(unmatched)} unmatched")

    if not playlist_entries:
        return {
            "status": "no_matches",
            "playlist": playlist_name,
            "matched": 0,
            "total": len(rows),
            "unmatched": unmatched,
            "message": "No tracks from the CSV were found in your Beets library.",
        }

    volumio_logger.info(f"[VOLUMIO] Pushing {len(playlist_entries)} tracks as '{playlist_name}'...")
    errors = await _push_playlist_via_socket(playlist_name, playlist_entries)

    volumio_logger.info(f"[VOLUMIO] === Done: {len(playlist_entries)} sent, {errors} errors ===")

    return {
        "status": "ok",
        "playlist": playlist_name,
        "matched": len(playlist_entries),
        "unmatched_count": len(unmatched),
        "total": len(rows),
        "volumio_errors": errors,
        "unmatched": unmatched[:20],
    }


@router.get("/volumio/playlists")
def list_volumio_playlists():
    import httpx
    try:
        resp = httpx.get(f"{VOLUMIO_HOST}/api/v1/listplaylists", timeout=5.0)
        return {"playlists": resp.json()}
    except Exception as e:
        raise HTTPException(502, f"Cannot reach Volumio: {e}")


# =============================================================
# SLSKD Proxy Routes
# =============================================================

@router.post("/slskd/searches")
async def slskd_search_proxy(payload: dict):
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{SLSKD_HOST}/api/v0/searches",
                headers=SLSKD_HEADERS,
                json=payload,
                timeout=15.0,
            )
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"SLSKD error: {e}")


@router.get("/slskd/searches/{search_id}")
async def slskd_poll_proxy(search_id: str):
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{SLSKD_HOST}/api/v0/searches/{search_id}",
                headers=SLSKD_HEADERS,
                timeout=15.0,
            )
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"SLSKD error: {e}")


@router.get("/slskd/searches/{search_id}/responses")
async def slskd_responses_proxy(search_id: str):
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{SLSKD_HOST}/api/v0/searches/{search_id}/responses",
                headers=SLSKD_HEADERS,
                timeout=15.0,
            )
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"SLSKD error: {e}")


@router.post("/slskd/downloads/{username}")
async def slskd_download_proxy(username: str, request: Request):
    import httpx
    try:
        raw_body = await request.body()
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{SLSKD_HOST}/api/v0/transfers/downloads/{username}",
                headers={**SLSKD_HEADERS, "Content-Type": "application/json"},
                content=raw_body,
                timeout=15.0,
            )
            return {"status": r.status_code, "ok": r.is_success}
    except httpx.HTTPError as e:
        raise HTTPException(502, f"SLSKD error: {e}")


@router.get("/slskd/transfers")
async def slskd_transfers_proxy():
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{SLSKD_HOST}/api/v0/transfers/downloads",
                headers=SLSKD_HEADERS,
                timeout=15.0,
            )
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"SLSKD error: {e}")
