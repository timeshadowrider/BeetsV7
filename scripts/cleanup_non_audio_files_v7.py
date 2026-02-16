#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import shutil
from pathlib import Path
import time

INBOX = Path("/inbox")
QUAR = Path("/music/quarantine/inbox_junk")

AUDIO_EXTS = {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aac"}
SAFE_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
SAFE_FILES = {"cover.jpg", "cover.png", "folder.jpg", "folder.png"}

INCOMPLETE_MARKERS = [
    ".UNPACK", ".PART", ".tmp", ".incomplete", ".partial"
]


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def is_audio(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_EXTS


def is_safe_image(path: Path) -> bool:
    if path.name.lower() in SAFE_FILES:
        return True
    return path.suffix.lower() in SAFE_IMAGE_EXTS


def is_incomplete_folder(path: Path) -> bool:
    return any(marker.lower() in path.name.lower() for marker in INCOMPLETE_MARKERS)


def should_skip(path: Path) -> bool:
    """Skip hidden/system files like .DS_Store, ._AppleDouble, etc."""
    if path.name.startswith("."):
        return True
    if path.name.lower() in {"thumbs.db", "desktop.ini"}:
        return True
    return False


def quarantine(path: Path, reason: str):
    QUAR.mkdir(parents=True, exist_ok=True)
    dest = QUAR / path.name
    log(f"[QUARANTINE] {path} -> {dest} ({reason})")
    try:
        shutil.move(str(path), str(dest))
    except Exception as e:
        log(f"[WARN] Failed to quarantine {path}: {e}")


def main():
    log("=== v7 Inbox Cleanup ===")
    log(f"Scanning: {INBOX}")

    for root, dirs, files in os.walk(INBOX):
        root_path = Path(root)

        # Handle incomplete folders first
        for d in dirs:
            dpath = root_path / d
            if is_incomplete_folder(dpath):
                quarantine(dpath, "incomplete download folder")

        # Handle files
        for fname in files:
            fpath = root_path / fname

            # Keep audio
            if is_audio(fpath):
                continue

            # Keep cover art
            if is_safe_image(fpath):
                continue

            # Skip hidden/system files
            if should_skip(fpath):
                continue

            # Everything else is junk
            quarantine(fpath, "non-audio file")

    log("=== Done (inbox cleanup) ===")


if __name__ == "__main__":
    main()
