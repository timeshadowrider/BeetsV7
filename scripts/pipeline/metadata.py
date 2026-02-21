#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pipeline Metadata Module - v7.7

Changes from v7.6:
- load_basic_tags: fixed path-based fallback for albumartist. When loose
  files sit directly in /inbox/Artist/ (no album subfolder), parent.parent
  resolves to /inbox and "inbox" was being used as the albumartist folder
  name, producing paths like /pre-library/inbox/Artist/track.flac. Now
  strips any fallback value that matches a known root directory name and
  uses INBOX.name as the reference to detect this case.
"""

from pathlib import Path
from collections import defaultdict
from mutagen import File as MutagenFile

from .util import INBOX

# Directory names that should never appear as an albumartist or album.
# If the path-based fallback resolves to one of these, substitute Unknown.
_FORBIDDEN_PATH_COMPONENTS = {
    INBOX.name,          # "inbox"
    "pre-library",
    "music",
    "library",
    "data",
    "app",
    "",
}


def load_basic_tags(path: Path):
    """
    Load albumartist and album tags from an audio file.

    FIX v7.6: Corrupted/unreadable files return a path-based fallback
    instead of (None, None), preventing all bad files from being grouped
    together under Unknown/Unknown Album in pre-library.

    FIX v7.7: Path-based fallback now guards against returning a root
    directory name (e.g. "inbox") as the albumartist. When a loose file
    sits at /inbox/Artist/track.flac, path.parent.parent is /inbox and
    path.parent.parent.name is "inbox" -- which then becomes the artist
    folder in pre-library, producing /pre-library/inbox/Artist/track.flac.
    We now check the fallback against _FORBIDDEN_PATH_COMPONENTS and use
    the INBOX parent directory as a safer fallback in that case.
    """
    try:
        audio = MutagenFile(path, easy=True)
        if audio is None:
            return path.parent.name, path.parent.name

        tags = dict(audio)

        def get(tag):
            val = tags.get(tag, [""])
            if isinstance(val, list):
                return val[0].strip() if val else None
            return str(val).strip() or None

        # Tag-based values (preferred)
        albumartist = get("albumartist") or get("artist")
        album = get("album")

        # Path-based fallbacks
        if not albumartist:
            candidate = path.parent.parent.name
            if candidate.lower() in _FORBIDDEN_PATH_COMPONENTS:
                # File is directly under INBOX root -- use immediate parent
                # (the artist folder name) as best available fallback
                albumartist = path.parent.name
            else:
                albumartist = candidate

        if not album:
            album = path.parent.name

        return albumartist, album

    except Exception:
        # Use directory names as fallback so files stay grouped with siblings
        candidate = path.parent.parent.name
        if candidate.lower() in _FORBIDDEN_PATH_COMPONENTS:
            albumartist = path.parent.name
        else:
            albumartist = candidate
        return albumartist, path.parent.name


def group_files_by_album(files):
    groups = defaultdict(list)
    for f in files:
        aa, al = load_basic_tags(f)
        groups[(aa, al)].append(f)
    return groups
