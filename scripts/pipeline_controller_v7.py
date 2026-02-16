#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
v7 Pipeline Controller (ASCII Safe)
Cleaned, modernized, and SLSKD-aware.
No Unicode punctuation. No em-dashes. No curly quotes.
"""

import os
import shutil
import subprocess
import time
import json
from pathlib import Path
from collections import defaultdict

import requests
from mutagen import File as MutagenFile

# ---------------------------------------------------------
# PATHS AND CONSTANTS
# ---------------------------------------------------------

INBOX = Path("/inbox")
PRELIB = Path("/pre-library")
LIBRARY = Path("/music/library")
DATA_DIR = Path("/data")

PIPELINE_LOG = DATA_DIR / "pipeline.log"
PIPELINE_VERBOSE_LOG = DATA_DIR / "pipeline_verbose.log"
PIPELINE_STATUS_JSON = DATA_DIR / "pipeline_status.json"

CHUNK_SIZE = 25
SETTLE_SECONDS = 3600
MAX_LOG_SIZE = 10 * 1024 * 1024

SLSKD_API_KEY = "PV1RixwWGOi91oVYfSMhd7JNVy1hj6jpcBOcdM+z1mKB+JnIQ2c4nwVWLgYi2JHd"


# ---------------------------------------------------------
# LOGGING
# ---------------------------------------------------------

def _ts():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _rotate_if_needed(path: Path):
    if path.exists() and path.stat().st_size > MAX_LOG_SIZE:
        backup = path.with_suffix(path.suffix + ".1")
        if backup.exists():
            backup.unlink()
        path.rename(backup)


def log(msg: str):
    _ensure_data_dir()
    line = "[%s] %s" % (_ts(), msg)
    print(line)
    _rotate_if_needed(PIPELINE_LOG)
    with open(PIPELINE_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def vlog(msg: str):
    _ensure_data_dir()
    line = "[%s] %s" % (_ts(), msg)
    print(line)
    _rotate_if_needed(PIPELINE_VERBOSE_LOG)
    with open(PIPELINE_VERBOSE_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def update_status(status: str, detail: str = "", current_artist: str = ""):
    _ensure_data_dir()
    payload = {
        "timestamp": _ts(),
        "status": status,
        "detail": detail,
        "current_artist": current_artist,
    }
    with open(PIPELINE_STATUS_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


# ---------------------------------------------------------
# SHELL HELPERS
# ---------------------------------------------------------

def run(cmd):
    vlog("RUN: %s" % " ".join(cmd))
    subprocess.run(cmd, check=False)


# ---------------------------------------------------------
# PERMISSIONS
# ---------------------------------------------------------

def fix_library_permissions():
    try:
        log("[PERMISSIONS] Fixing library permissions...")
        subprocess.run(["chown", "-R", "1000:1000", str(LIBRARY)], check=False)
        subprocess.run(["find", str(LIBRARY), "-type", "d", "-exec", "chmod", "2777", "{}", "+"], check=False)
        subprocess.run(["find", str(LIBRARY), "-type", "f", "-exec", "chmod", "0666", "{}", "+"], check=False)
        log("[PERMISSIONS] Library permissions corrected.")
    except Exception as e:
        log("[PERMISSIONS] ERROR: %s" % e)


# ---------------------------------------------------------
# NAVIDROME / SUBSONIC
# ---------------------------------------------------------

def trigger_subsonic_scan_from_config():
    host = "http://10.0.0.100"
    port = 4533
    user = "timeshadowrider"
    password = "An|t@theR@bb|t"
    url = "%s:%s/rest/startScan" % (host, port)

    params = {"u": user, "p": password, "v": "1.13.0", "c": "beets", "f": "json"}

    try:
        log("[SUBSONIC] Triggering Navidrome scan at %s" % url)
        r = requests.get(url, params=params, timeout=10)
        log("[SUBSONIC] Response %s: %s" % (r.status_code, r.text[:200]))
    except Exception as e:
        log("[SUBSONIC] Scan trigger failed: %s" % e)


# ---------------------------------------------------------
# VOLUMIO
# ---------------------------------------------------------

def trigger_volumio_rescan():
    try:
        log("[VOLUMIO] Triggering Volumio rescan...")
        subprocess.run(["ssh", "volumio@10.0.0.102", "volumio", "rescan"], check=False)
        log("[VOLUMIO] Rescan triggered.")
    except Exception as e:
        log("[VOLUMIO] ERROR triggering rescan: %s" % e)


# ---------------------------------------------------------
# INBOX CLEANUP
# ---------------------------------------------------------

def cleanup_inbox_junk(artist_folder: Path):
    AUDIO_EXTS = {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".wav"}

    try:
        for item in artist_folder.iterdir():
            if item.is_file() and item.suffix.lower() not in AUDIO_EXTS:
                vlog("[CLEANUP] Removing junk file: %s" % item)
                item.unlink(missing_ok=True)

        for root, dirs, files in os.walk(artist_folder, topdown=False):
            p = Path(root)
            if p != artist_folder and not any(p.iterdir()):
                vlog("[CLEANUP] Removing empty folder: %s" % p)
                p.rmdir()
    except FileNotFoundError:
        vlog("[CLEANUP] Folder disappeared during cleanup: %s" % artist_folder)


# ---------------------------------------------------------
# SETTLE CHECK
# ---------------------------------------------------------

def folder_is_settled(path, min_age_seconds=SETTLE_SECONDS):
    newest_mtime = 0
    for root, dirs, files in os.walk(path):
        for f in files:
            try:
                mtime = (Path(root) / f).stat().st_mtime
                if mtime > newest_mtime:
                    newest_mtime = mtime
            except FileNotFoundError:
                pass

    if newest_mtime == 0:
        return True

    age = time.time() - newest_mtime
    vlog("SETTLE CHECK: %s age=%.1fs threshold=%ss" % (path, age, min_age_seconds))
    return age >= min_age_seconds


# ---------------------------------------------------------
# SABNZBD AWARENESS
# ---------------------------------------------------------

def sabnzbd_is_processing(artist_folder: Path) -> bool:
    try:
        url = "http://10.0.0.100:8080/api"
        params = {"mode": "queue", "output": "json", "apikey": "5c938b2911c14463a435cea4964679bc"}
        r = requests.get(url, params=params, timeout=5)
        data = r.json()

        for job in data.get("queue", {}).get("slots", []):
            if job.get("status") != "Completed":
                if Path(job.get("storage", "")).name == artist_folder.name:
                    vlog("[SABNZBD] Active job for %s" % artist_folder)
                    return True
        return False
    except Exception as e:
        log("[SABNZBD] Error checking status: %s" % e)
        return False


# ---------------------------------------------------------
# SLSKD AWARENESS (FIXED)
# ---------------------------------------------------------

def slskd_is_processing(artist_folder: Path) -> bool:
    """
    Uses SLSKD v0 API with API key authentication.
    Returns True if SLSKD is downloading anything for this artist.
    """
    try:
        r = requests.get(
            "http://10.0.0.100:5030/api/v0/transfers",
            headers={"X-API-Key": SLSKD_API_KEY},
            timeout=5,
        )
        transfers = r.json()

        for t in transfers:
            state = t.get("state")
            path = t.get("path", "")

            if state not in ("completed", "succeeded"):
                if Path(path).name == artist_folder.name:
                    vlog("[SLSKD] Active transfer for %s state=%s" % (artist_folder, state))
                    return True

        return False

    except Exception as e:
        log("[SLSKD] Error checking status: %s" % e)
        return False


# ---------------------------------------------------------
# ARTIST FOLDER LISTING
# ---------------------------------------------------------

def list_artist_folders():
    if not INBOX.exists():
        return []
    return [
        p for p in sorted(INBOX.iterdir())
        if p.is_dir() and not p.name.startswith("_UNPACK_") and p.name != "failed_imports"
    ]


# ---------------------------------------------------------
# EMPTY TREE CLEANUP
# ---------------------------------------------------------

def cleanup_empty_inbox_tree(path):
    while path != INBOX and path.exists() and not any(path.iterdir()):
        vlog("RM EMPTY: %s" % path)
        path.rmdir()
        path = path.parent


# ---------------------------------------------------------
# METADATA HELPERS
# ---------------------------------------------------------

def load_basic_tags(path: Path):
    try:
        audio = MutagenFile(path, easy=True)
        if audio is None:
            return None, None
        tags = dict(audio)

        def get(tag):
            return tags.get(tag, [""])[0].strip() or None

        return get("albumartist") or get("artist"), get("album")
    except Exception:
        return None, None


def group_files_by_album(files):
    groups = defaultdict(list)
    for f in files:
        aa, al = load_basic_tags(f)
        groups[(aa, al)].append(f)
    return groups


def safe_folder_name(text: str | None) -> str:
    return (text or "Unknown").replace("/", "-").strip()


def ensure_album_folder_in_prelib(albumartist, album):
    aa = safe_folder_name(albumartist)
    al = safe_folder_name(album)
    dst = PRELIB / aa / al
    dst.mkdir(parents=True, exist_ok=True)
    return dst


def move_group_to_prelibrary(albumartist, album, files):
    dst_folder = ensure_album_folder_in_prelib(albumartist, album)
    for src in files:
        dst = dst_folder / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))


def move_existing_album_folder_to_prelibrary(src_album_folder: Path):
    rel = src_album_folder.relative_to(INBOX)
    dst = PRELIB / rel
    dst.parent.mkdir(parents=True, exist_ok=True)

    if dst.exists():
        for root, dirs, files in os.walk(src_album_folder):
            for f in files:
                src_file = Path(root) / f
                rel_file = src_file.relative_to(src_album_folder)
                dst_file = dst / rel_file
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src_file), str(dst_file))
        shutil.rmtree(src_album_folder)
    else:
        shutil.move(str(src_album_folder), str(dst))


# ---------------------------------------------------------
# BEETS IMPORT
# ---------------------------------------------------------

def run_beets_import_on_prelibrary():
    if PRELIB.exists():
        run(["beet", "import", "-q", str(PRELIB)])


def run_post_import_pipeline():
    run(["beet", "update", "path:/pre-library"])
    run(["beet", "move", "-d", str(LIBRARY), "path:/pre-library"])
    run(["beet", "update", "path:%s" % LIBRARY])


# ---------------------------------------------------------
# MAIN PIPELINE
# ---------------------------------------------------------

def process_artist_folder(artist_folder: Path):
    if artist_folder.name in ("failed_imports",) or artist_folder.name.startswith("_UNPACK_"):
        return

    if sabnzbd_is_processing(artist_folder):
        log("[SKIP] SABnzbd still processing: %s" % artist_folder)
        return

    if slskd_is_processing(artist_folder):
        log("[SKIP] SLSKD still processing: %s" % artist_folder)
        return

    if not folder_is_settled(artist_folder, min_age_seconds=300):
        log("[SKIP] Grace period not met: %s" % artist_folder)
        return

    log("ARTIST: %s" % artist_folder)
    update_status("running", "processing artist", artist_folder.name)

    cleanup_inbox_junk(artist_folder)

    try:
        subdirs = [p for p in sorted(artist_folder.iterdir()) if p.is_dir() and p.name != "failed_imports"]
    except FileNotFoundError:
        return

    for sub in subdirs:
        if folder_is_settled(sub, min_age_seconds=SETTLE_SECONDS):
            move_existing_album_folder_to_prelibrary(sub)
        else:
            log("[SKIP] Album subfolder not settled: %s" % sub)

    try:
        loose_files = [p for p in sorted(artist_folder.iterdir()) if p.is_file()]
    except FileNotFoundError:
        return

    audio_loose = [p for p in loose_files if p.suffix.lower() in {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aac"}]

    if audio_loose:
        groups = group_files_by_album(audio_loose)
        for (aa, al), files in groups.items():
            if len(files) > CHUNK_SIZE:
                for i in range(0, len(files), CHUNK_SIZE):
                    chunk = files[i:i + CHUNK_SIZE]
                    move_group_to_prelibrary(aa or artist_folder.name, al or "Unknown Album", chunk)
                    run(["python3", "/app/scripts/fingerprint_all.py"])
                    run_beets_import_on_prelibrary()
                    run_post_import_pipeline()
            else:
                move_group_to_prelibrary(aa or artist_folder.name, al or "Unknown Album", files)
                run(["python3", "/app/scripts/fingerprint_all.py"])
                run_beets_import_on_prelibrary()
                run_post_import_pipeline()

    try:
        if not any(artist_folder.iterdir()):
            cleanup_empty_inbox_tree(artist_folder)
    except FileNotFoundError:
        pass


def main():
    _ensure_data_dir()
    log("=== v7 Pipeline Controller (ASCII Safe, SLSKD Aware) ===")
    update_status("running", "starting pipeline")

    try:
        from pipeline.quarantine import quarantine_failed_imports_global
        from pipeline.regenerate import generate_ui_json

        quarantine_failed_imports_global(PRELIB)

        artists = list_artist_folders()
        if not artists:
            log("Inbox empty - nothing to do.")
            update_status("idle", "inbox empty")
            return

        for artist in artists:
            process_artist_folder(artist)

        generate_ui_json()
        fix_library_permissions()
        trigger_subsonic_scan_from_config()
        trigger_volumio_rescan()

        log("=== v7 Pipeline Finished ===")
        update_status("success", "pipeline finished")

    except Exception as e:
        log("[ERROR] Pipeline crashed: %s" % e)
        update_status("error", str(e))
        raise


if __name__ == "__main__":
    main()
