#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import shutil
from pathlib import Path

from .logging import vlog
from .util import PRELIB, safe_folder_name


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

    rel = src_album_folder.relative_to(src_album_folder.parent.parent)
    dst = PRELIB / rel
    dst.parent.mkdir(parents=True, exist_ok=True)

    try:
        shutil.move(str(src_album_folder), str(dst))
    except FileNotFoundError:
        vlog("[ALBUM-MOVE] Folder vanished: %s" % src_album_folder)
    except Exception as e:
        vlog("[ALBUM-MOVE] Error moving folder %s -> %s: %s" %
             (src_album_folder, dst, e))
