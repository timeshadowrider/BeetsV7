#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
from collections import defaultdict
from mutagen import File as MutagenFile


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
