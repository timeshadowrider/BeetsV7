"""
Shared beet search helpers used by the Volumio and Navidrome playlist builders.
All subprocess calls use list args (no shell=True) to prevent injection.
"""

import re
import subprocess
import unicodedata
import logging
from typing import Optional

_BEETS_LIBRARY_PREFIX = "/music/library/"

log = logging.getLogger(__name__)


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9 ]", "", s.lower())
    return s.strip()


def primary_artist(artist: str) -> str:
    return artist.replace(";", ",").split(",")[0].strip()


def beet_query(title: str, artist: str = "", logger: Optional[logging.Logger] = None) -> Optional[str]:
    logger = logger or log
    norm_title = normalize(title)
    cmd = ["beet", "ls", "-p", f"title:{norm_title}"]
    if artist:
        cmd.append(f"artist:{normalize(artist)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        return lines[0] if lines else None
    except Exception as e:
        logger.error(f"beet query error ({cmd!r}): {e}")
        return None


def artist_matches(
    beets_path: str,
    expected_artist: str,
    library_prefix: str = _BEETS_LIBRARY_PREFIX,
    logger: Optional[logging.Logger] = None,
) -> bool:
    logger = logger or log
    if not expected_artist:
        return True
    relative = beets_path.replace(library_prefix, "")
    path_artist = relative.split("/")[0]
    norm_path = normalize(path_artist)
    if not norm_path:
        logger.warning(f"Could not extract artist from path: {beets_path}")
        return False
    all_artists = [a.strip() for a in expected_artist.replace(";", ",").split(",") if a.strip()]
    for candidate in all_artists:
        norm_candidate = normalize(candidate)
        if norm_candidate in norm_path or norm_path in norm_candidate:
            logger.info(f"Artist verified: path='{path_artist}' matches '{candidate}'")
            return True
    logger.warning(f"Artist mismatch: path='{path_artist}' not in {all_artists}")
    return False


def search_beets_for_track(
    title: str,
    artist: str,
    library_prefix: str = _BEETS_LIBRARY_PREFIX,
    logger: Optional[logging.Logger] = None,
) -> Optional[str]:
    logger = logger or log
    logger.info(f"Searching: '{artist} - {title}'")

    path = beet_query(title, artist, logger)
    if path:
        logger.info(f"MATCH pass1 (full artist): {path}")
        return path

    prim = primary_artist(artist)
    if prim != artist and prim:
        path = beet_query(title, prim, logger)
        if path:
            logger.info(f"MATCH pass2 (primary artist): {path}")
            return path

    path = beet_query(title, logger=logger)
    if path:
        if artist_matches(path, artist, library_prefix, logger):
            logger.info(f"MATCH pass3 (title+artist verified): {path}")
            return path
        else:
            logger.warning(f"REJECTED pass3 (wrong artist): {path}")

    logger.warning(f"NO MATCH: '{artist} - {title}'")
    return None
