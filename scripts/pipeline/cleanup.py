#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from pathlib import Path

from .logging import vlog
from .util import INBOX


AUDIO_EXTS = {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".wav"}


def cleanup_inbox_junk(artist_folder: Path):
    try:
        for item in artist_folder.iterdir():
            if item.is_file() and item.suffix.lower() not in AUDIO_EXTS:
                vlog("[CLEANUP] Removing junk file: %s" % item)
                try:
                    item.unlink()
                except FileNotFoundError:
                    vlog("[CLEANUP] File disappeared: %s" % item)
                except Exception as e:
                    vlog("[CLEANUP] Could not delete %s: %s" % (item, e))

        for root, dirs, files in os.walk(artist_folder, topdown=False):
            p = Path(root)
            if p != artist_folder:
                try:
                    if not any(p.iterdir()):
                        vlog("[CLEANUP] Removing empty folder: %s" % p)
                        p.rmdir()
                except FileNotFoundError:
                    vlog("[CLEANUP] Folder disappeared: %s" % p)
                except Exception as e:
                    vlog("[CLEANUP] Could not remove %s: %s" % (p, e))

    except FileNotFoundError:
        vlog("[CLEANUP] Folder disappeared during cleanup: %s" % artist_folder)


def cleanup_empty_inbox_tree(path: Path):
    while path != INBOX and path.exists():
        try:
            if any(path.iterdir()):
                break
            vlog("RM EMPTY: %s" % path)
            path.rmdir()
            path = path.parent
        except FileNotFoundError:
            vlog("[EMPTY] Folder disappeared: %s" % path)
            break
        except Exception as e:
            vlog("[EMPTY] Could not remove %s: %s" % (path, e))
            break
