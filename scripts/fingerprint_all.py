#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import subprocess
import json
from pathlib import Path
from mutagen import File as MutagenFile
import shutil
import time

PRELIB = Path("/pre-library")
QUAR = Path("/music/quarantine")
FP_DB = Path("/app/data/fingerprints.json")  # safe location

AUDIO_EXTS = {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aac"}


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def load_fp_db():
    if FP_DB.exists():
        try:
            return json.loads(FP_DB.read_text())
        except:
            return {}
    return {}


def save_fp_db(db):
    FP_DB.parent.mkdir(parents=True, exist_ok=True)
    FP_DB.write_text(json.dumps(db, indent=2))


def is_audio_file(path):
    return path.suffix.lower() in AUDIO_EXTS


def run_fpcalc(path):
    """Run Chromaprint fpcalc and return fingerprint + duration."""
    try:
        result = subprocess.run(
            ["fpcalc", "-json", str(path)],
            capture_output=True,
            text=True,
            check=True
        )
        data = json.loads(result.stdout)
        return data.get("fingerprint"), data.get("duration")
    except Exception as e:
        log(f"[ERROR] fpcalc failed: {path} ({e})")
        return None, None


def ffprobe_check(path):
    """Validate audio integrity using ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
            capture_output=True,
            text=True,
            check=True
        )
        data = json.loads(result.stdout)
        return float(data["format"]["duration"]) > 0
    except:
        return False


def read_tags(path):
    """Read metadata tags using Mutagen."""
    try:
        audio = MutagenFile(path, easy=True)
        if audio is None:
            return {}
        return dict(audio)
    except:
        return {}


def has_garbage_metadata(tags):
    """Detect missing or garbage metadata."""
    bad_values = {"", "unknown", "untitled", "track 01", "track01", "n/a"}
    fields = ["artist", "album", "title"]

    for f in fields:
        val = tags.get(f, [""])[0].strip().lower()
        if val in bad_values:
            return True

    return False


def folder_tag_mismatch(path, tags):
    """Detect mismatch between folder structure and tags."""
    parts = path.parts
    if len(parts) < 3:
        return False

    folder_artist = parts[-3].lower()
    folder_album = parts[-2].lower()

    tag_artist = tags.get("artist", [""])[0].lower()
    tag_album = tags.get("album", [""])[0].lower()

    if tag_artist and tag_artist not in folder_artist:
        return True
    if tag_album and tag_album not in folder_album:
        return True

    return False


def quarantine(path, reason):
    dest = QUAR / path.name
    QUAR.mkdir(parents=True, exist_ok=True)
    log(f"[QUARANTINE] {path} -> {dest} ({reason})")
    shutil.move(str(path), str(dest))


def main():
    log("=== v7 Fingerprint Pass (pre-library) ===")

    fp_db = load_fp_db()

    for root, dirs, files in os.walk(PRELIB):
        for f in files:
            path = Path(root) / f
            if not is_audio_file(path):
                continue

            log(f"[SCAN] {path}")

            # 1. Audio integrity check
            if not ffprobe_check(path):
                quarantine(path, "ffprobe integrity failure")
                continue

            # 2. Fingerprint
            fp, duration = run_fpcalc(path)
            if not fp:
                quarantine(path, "fingerprint failure")
                continue

            fp_db[str(path)] = {"fingerprint": fp, "duration": duration}

            # 3. Metadata inspection
            tags = read_tags(path)

            if has_garbage_metadata(tags):
                log(f"[WARN] Garbage metadata: {path}")

            if folder_tag_mismatch(path, tags):
                log(f"[WARN] Folder/tag mismatch: {path}")

    save_fp_db(fp_db)
    log("=== Done fingerprinting pre-library ===")


if __name__ == "__main__":
    main()
