#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
from collections import defaultdict
from mutagen import File as MutagenFile


def load_basic_tags(path: Path):
    """
    Load albumartist and album tags from an audio file.

    FIX: Corrupted/unreadable files now return a path-based fallback
    instead of (None, None), preventing all bad files from being grouped
    together under Unknown/Unknown Album in pre-library.
    """
    try:
        audio = MutagenFile(path, easy=True)
        if audio is None:
            # Unrecognised format - use filename as fallback
            return path.parent.name, path.parent.name

        tags = dict(audio)

        def get(tag):
            val = tags.get(tag, [""])
            if isinstance(val, list):
                return val[0].strip() if val else None
            return str(val).strip() or None

        albumartist = get("albumartist") or get("artist") or path.parent.parent.name
        album = get("album") or path.parent.name

        return albumartist, album

    except Exception:
        # Use directory names as fallback so files stay grouped with siblings
        return path.parent.parent.name, path.parent.name


def group_files_by_album(files):
    groups = defaultdict(list)
    for f in files:
        aa, al = load_basic_tags(f)
        groups[(aa, al)].append(f)
    return groups
