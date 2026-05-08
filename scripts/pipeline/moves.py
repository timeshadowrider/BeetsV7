#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pipeline Moves Module - v7.7

Changes from v7.6:
- Added PreLibraryFullError exception raised on ENOSPC ([Errno 28]) so
  the pipeline controller can catch mid-run tmpfs-full conditions rather
  than silently skipping files.
"""

import errno
import shutil
import time
from pathlib import Path

from .logging import vlog, log
from .util import PRELIB, INBOX, safe_folder_name


class PreLibraryFullError(Exception):
    """Raised when a move to /pre-library fails with ENOSPC ([Errno 28])."""
    pass


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

        # Handle destination collision
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
        except OSError as e:
            if e.errno == errno.ENOSPC:
                log("[MOVE] ENOSPC moving %s -> %s" % (src, dst))
                raise PreLibraryFullError(
                    "Pre-library tmpfs full while moving: %s" % src.name
                )
            else:
                log("[MOVE] Error moving %s -> %s: %s" % (src, dst, e))
        except Exception as e:
            log("[MOVE] Error moving %s -> %s: %s" % (src, dst, e))


def move_existing_album_folder_to_prelibrary(src_album_folder: Path):
    if not src_album_folder.exists():
        vlog("[ALBUM-MOVE] Folder disappeared: %s" % src_album_folder)
        return

    try:
        rel = src_album_folder.relative_to(INBOX)
    except ValueError:
        log("[ALBUM-MOVE] WARNING: %s is not under INBOX, using folder name only" % src_album_folder)
        rel = Path(src_album_folder.name)

    dst = PRELIB / rel
    dst.parent.mkdir(parents=True, exist_ok=True)

    # Handle destination collision
    if dst.exists():
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        dst = PRELIB / (str(rel) + "_" + timestamp)
        vlog("[ALBUM-MOVE] Destination exists, using: %s" % dst)

    try:
        shutil.move(str(src_album_folder), str(dst))
    except FileNotFoundError:
        vlog("[ALBUM-MOVE] Folder vanished: %s" % src_album_folder)
    except OSError as e:
        if e.errno == errno.ENOSPC:
            log("[ALBUM-MOVE] ENOSPC moving folder %s" % src_album_folder.name)
            raise PreLibraryFullError(
                "Pre-library tmpfs full while moving folder: %s" % src_album_folder.name
            )
        else:
            log("[ALBUM-MOVE] Error moving folder %s -> %s: %s" % (src_album_folder, dst, e))
    except Exception as e:
        log("[ALBUM-MOVE] Error moving folder %s -> %s: %s" % (src_album_folder, dst, e))
