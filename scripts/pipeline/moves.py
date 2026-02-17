#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import shutil
from pathlib import Path

from .logging import vlog, log
from .util import PRELIB, INBOX, safe_folder_name


def ensure_album_folder(albumartist, album):
    aa = safe_folder_name(albumartist)
    al = safe_folder_name(album)
    dst = PRELIB / aa / al
    dst.mkdir(parents=True, exist_ok=True)
    return dst


def move_group_to_prelibrary(albumartist, album, files):
    dst_folder = ensure_album_folder(albumartist, album)

    for src in files:
        if not src.exists():
            vlog("[MOVE] File disappeared: %s" % src)
            continue

        dst = dst_folder / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)

        # FIX: Handle destination collision - don't silently overwrite
        if dst.exists():
            stem = dst.stem
            suffix = dst.suffix
            counter = 1
            while dst.exists():
                dst = dst_folder / ("%s_%d%s" % (stem, counter, suffix))
                counter += 1
            vlog("[MOVE] Destination collision, using: %s" % dst.name)

        try:
            shutil.move(str(src), str(dst))
        except FileNotFoundError:
            vlog("[MOVE] File vanished: %s" % src)
        except Exception as e:
            vlog("[MOVE] Error moving %s -> %s: %s" % (src, dst, e))


def move_existing_album_folder_to_prelibrary(src_album_folder: Path):
    if not src_album_folder.exists():
        vlog("[ALBUM-MOVE] Folder disappeared: %s" % src_album_folder)
        return

    # FIX: Was using relative_to(parent.parent) which assumes exactly 2 levels
    # deep (/inbox/Artist/Album). Now safely builds destination from INBOX root.
    try:
        rel = src_album_folder.relative_to(INBOX)
    except ValueError:
        # Not under INBOX - use just the folder name as fallback
        log("[ALBUM-MOVE] WARNING: %s is not under INBOX, using folder name only" % src_album_folder)
        rel = Path(src_album_folder.name)

    dst = PRELIB / rel
    dst.parent.mkdir(parents=True, exist_ok=True)

    # FIX: Handle destination collision
    if dst.exists():
        import time
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        dst = PRELIB / (str(rel) + "_" + timestamp)
        vlog("[ALBUM-MOVE] Destination exists, using: %s" % dst)

    try:
        shutil.move(str(src_album_folder), str(dst))
    except FileNotFoundError:
        vlog("[ALBUM-MOVE] Folder vanished: %s" % src_album_folder)
    except Exception as e:
        log("[ALBUM-MOVE] Error moving folder %s -> %s: %s" % (src_album_folder, dst, e))
