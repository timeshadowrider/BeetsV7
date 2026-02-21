#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/pipeline/dedup.py

RAM-based pre-import deduplication.

Runs after files are staged in /pre-library (tmpfs) but before beets import.
Three-tier approach:

  Tier 1 - Tag-based (fast, no network):
    Groups tracks by normalized title within each album group.
    If the same title appears in multiple formats, scores each by quality
    and keeps the best. Zero network calls, completes in milliseconds.

  Tier 2 - Fingerprint-based (slower, catches bad/missing tags):
    Runs fpcalc on tracks not resolved by Tier 1.
    Compares chromaprint fingerprints within each album group.
    If similarity exceeds threshold, keeps the higher quality file.

  Tier 3 - MusicBrainz confirmation (optional, network):
    For borderline Tier 2 matches, queries AcoustID to get MB recording ID.
    If both tracks resolve to the same recording, confirms the duplicate.
    Controlled by DEDUP_USE_MUSICBRAINZ env var (default: true).

Rejected files are moved to /tmp/pipeline-work/dedup_rejected/ for review.
A dedup log is written to /data/dedup.log.

Quality scoring (higher = better):
  Format:      FLAC(100) > ALAC(95) > M4A(80) > OGG(70) > MP3(60)
  Bit depth:   24 > 16 > 8
  Sample rate: 192k > 96k > 48k > 44.1k
  Bitrate:     320 > 256 > 192 > 128
"""

import os
import re
import shutil
import subprocess
import time
import unicodedata
import logging
from pathlib import Path
from collections import defaultdict
from typing import Optional

from mutagen import File as MutagenFile

# Optional imports - graceful degradation if not available
try:
    import acoustid
    ACOUSTID_AVAILABLE = True
except ImportError:
    ACOUSTID_AVAILABLE = False

try:
    import musicbrainzngs
    musicbrainzngs.set_useragent("BeetsV7Dedup", "1.0", "https://github.com/beetsv7")
    MB_AVAILABLE = True
except ImportError:
    MB_AVAILABLE = False

# Config
DEDUP_REJECTED_DIR = Path("/tmp/pipeline-work/dedup_rejected")
DEDUP_LOG = Path("/data/dedup.log")
ACOUSTID_API_KEY = "ToQiZOt39C"  # matches config.yaml

# Fingerprint similarity threshold (0.0-1.0)
# 0.85 = same recording, allows for minor encoding differences
FP_SIMILARITY_THRESHOLD = 0.85

# Format quality scores - higher is better
FORMAT_SCORE = {
    "flac": 100,
    "alac": 95,
    "aiff": 90,
    "wav":  85,
    "m4a":  80,
    "ogg":  70,
    "mp3":  60,
    "aac":  55,
    "wma":  40,
}

AUDIO_EXTS = {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aac"}

# Use MusicBrainz for borderline fingerprint matches
USE_MUSICBRAINZ = os.getenv("DEDUP_USE_MUSICBRAINZ", "true").lower() == "true"

# Set up dedicated dedup logger
dedup_logger = logging.getLogger("dedup")
dedup_logger.setLevel(logging.DEBUG)
if not dedup_logger.handlers:
    DEDUP_LOG.parent.mkdir(parents=True, exist_ok=True)
    _fh = logging.FileHandler(str(DEDUP_LOG))
    _fh.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", "%H:%M:%S"))
    dedup_logger.addHandler(_fh)


def dlog(msg: str):
    dedup_logger.info(msg)
    print("[DEDUP] %s" % msg)


# ---------------------------------------------------------------------------
# Quality scoring
# ---------------------------------------------------------------------------

def _get_format(path: Path) -> str:
    """Extract format string from mutagen mime type."""
    try:
        audio = MutagenFile(path)
        if audio and hasattr(audio, "mime") and audio.mime:
            mime = audio.mime[0].lower()
            for fmt in FORMAT_SCORE:
                if fmt in mime:
                    return fmt
        # Fall back to extension
        return path.suffix.lower().lstrip(".")
    except Exception:
        return path.suffix.lower().lstrip(".")


def quality_score(path: Path) -> int:
    """
    Compute a single integer quality score for a file.
    Higher = better quality.

    Score breakdown (to avoid lower-tier values overriding higher-tier ones):
      format    * 1_000_000
      bit_depth *    10_000
      sample_khz *     100
      bitrate_kbps *     1
    """
    try:
        audio = MutagenFile(path)
        if audio is None:
            return 0

        fmt = _get_format(path)
        fmt_score = FORMAT_SCORE.get(fmt, 50)

        bit_depth = getattr(audio.info, "bits_per_sample", 16) or 16
        sample_rate = getattr(audio.info, "sample_rate", 44100) or 44100
        bitrate = getattr(audio.info, "bitrate", 0) or 0

        return (
            fmt_score          * 1_000_000 +
            bit_depth          *    10_000 +
            (sample_rate // 1000) *   100 +
            (bitrate // 1000)
        )
    except Exception:
        return 0


def quality_label(path: Path) -> str:
    """Human-readable quality string for logging."""
    try:
        audio = MutagenFile(path)
        if audio is None:
            return path.suffix
        fmt = _get_format(path).upper()
        bit_depth = getattr(audio.info, "bits_per_sample", None)
        sample_rate = getattr(audio.info, "sample_rate", None)
        bitrate = getattr(audio.info, "bitrate", None)

        parts = [fmt]
        if bit_depth and bit_depth > 0:
            parts.append("%dbit" % bit_depth)
        if sample_rate:
            parts.append("%gkHz" % (sample_rate / 1000))
        if bitrate and not bit_depth:  # only show bitrate for lossy
            parts.append("%dk" % (bitrate // 1000))
        return "/".join(parts)
    except Exception:
        return path.suffix


# ---------------------------------------------------------------------------
# Tag normalization
# ---------------------------------------------------------------------------

def _normalize_title(s: str) -> str:
    """
    Normalize a track title for comparison.
    Strips diacritics, lowercases, removes punctuation and common suffixes
    like '- remastered', '(feat. x)', '(bonus track)' etc.
    """
    if not s:
        return ""
    # Strip diacritics
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    # Remove common version/feature suffixes
    s = re.sub(
        r'\s*[-–(]\s*(?:feat\.?|ft\.?|featuring|remaster(?:ed)?|'
        r'bonus track|live|demo|acoustic|radio edit|single version|'
        r'explicit|clean|album version)\b.*$',
        "", s, flags=re.IGNORECASE
    )
    # Remove all non-alphanumeric
    s = re.sub(r"[^a-z0-9]", "", s)
    return s.strip()


def _get_title(path: Path) -> str:
    """Read title tag from file, fall back to stem."""
    try:
        audio = MutagenFile(path, easy=True)
        if audio and audio.tags:
            title = audio.tags.get("title", [""])[0]
            return title.strip() if title else path.stem
    except Exception:
        pass
    return path.stem


# ---------------------------------------------------------------------------
# Tier 1: Tag-based deduplication
# ---------------------------------------------------------------------------

def tier1_dedup(files: list[Path]) -> tuple[list[Path], list[tuple[Path, Path, str]]]:
    """
    Group files by normalized title. For each group with >1 file,
    keep the highest quality version.

    Returns:
        keepers: list of files to keep
        rejected: list of (rejected_path, kept_path, reason) tuples
    """
    # Group by normalized title
    by_title = defaultdict(list)
    for f in files:
        norm = _normalize_title(_get_title(f))
        by_title[norm].append(f)

    keepers = []
    rejected = []

    for norm_title, group in by_title.items():
        if len(group) == 1:
            keepers.append(group[0])
            continue

        # Score all files in group
        scored = sorted(group, key=quality_score, reverse=True)
        winner = scored[0]
        keepers.append(winner)

        for loser in scored[1:]:
            reason = "tag-dedup: '%s' kept %s over %s" % (
                norm_title,
                quality_label(winner),
                quality_label(loser),
            )
            rejected.append((loser, winner, reason))
            dlog("TIER1 REJECT: %s -> keeping %s (%s > %s)" % (
                loser.name, winner.name,
                quality_label(winner), quality_label(loser)
            ))

    return keepers, rejected


# ---------------------------------------------------------------------------
# Tier 2: Fingerprint-based deduplication
# ---------------------------------------------------------------------------

def _run_fpcalc(path: Path) -> Optional[str]:
    """Run fpcalc and return fingerprint string, or None on failure."""
    try:
        result = subprocess.run(
            ["fpcalc", "-raw", str(path)],
            capture_output=True, text=True, timeout=30
        )
        for line in result.stdout.splitlines():
            if line.startswith("FINGERPRINT="):
                return line.split("=", 1)[1].strip()
    except Exception as e:
        dlog("fpcalc failed for %s: %s" % (path.name, e))
    return None


def _fp_similarity(fp1: str, fp2: str) -> float:
    """
    Compute similarity between two raw chromaprint fingerprints.
    Chromaprint fingerprints are comma-separated integers.
    Uses bit-level Hamming distance on the integer arrays.
    Returns 0.0-1.0 where 1.0 = identical.
    """
    try:
        a = [int(x) for x in fp1.split(",") if x.strip()]
        b = [int(x) for x in fp2.split(",") if x.strip()]
        if not a or not b:
            return 0.0

        # Compare over the shorter length
        length = min(len(a), len(b))
        # Use only first 120 values (covers ~30 seconds) for speed
        length = min(length, 120)
        a, b = a[:length], b[:length]

        matching_bits = 0
        total_bits = length * 32

        for x, y in zip(a, b):
            xor = x ^ y
            # Count zero bits (matching bits)
            matching_bits += 32 - bin(xor).count("1")

        return matching_bits / total_bits
    except Exception:
        return 0.0


def tier2_dedup(files: list[Path]) -> tuple[list[Path], list[tuple[Path, Path, str]]]:
    """
    Fingerprint all files and find duplicates by chromaprint similarity.

    Returns:
        keepers: files to keep
        rejected: list of (rejected, kept, reason) tuples
    """
    if len(files) <= 1:
        return files, []

    dlog("TIER2: fingerprinting %d files..." % len(files))

    # Build fingerprint map
    fp_map = {}
    for f in files:
        fp = _run_fpcalc(f)
        if fp:
            fp_map[f] = fp
        else:
            dlog("TIER2: no fingerprint for %s, skipping" % f.name)

    if not fp_map:
        return files, []

    keepers = []
    rejected = []
    processed = set()

    fp_files = list(fp_map.keys())

    for i, f1 in enumerate(fp_files):
        if f1 in processed:
            continue

        duplicates = [f1]

        for f2 in fp_files[i+1:]:
            if f2 in processed:
                continue
            sim = _fp_similarity(fp_map[f1], fp_map[f2])
            if sim >= FP_SIMILARITY_THRESHOLD:
                dlog("TIER2: similarity %.3f between %s and %s" % (
                    sim, f1.name, f2.name))
                duplicates.append(f2)
                processed.add(f2)

        if len(duplicates) > 1:
            # Check MusicBrainz if available and enabled
            if USE_MUSICBRAINZ and MB_AVAILABLE and ACOUSTID_AVAILABLE:
                duplicates = _mb_confirm(duplicates, fp_map)

            scored = sorted(duplicates, key=quality_score, reverse=True)
            winner = scored[0]
            keepers.append(winner)
            for loser in scored[1:]:
                sim = _fp_similarity(fp_map.get(winner, ""), fp_map.get(loser, ""))
                reason = "fp-dedup: similarity=%.3f kept %s over %s" % (
                    sim, quality_label(winner), quality_label(loser)
                )
                rejected.append((loser, winner, reason))
                dlog("TIER2 REJECT: %s -> keeping %s (%s > %s, sim=%.3f)" % (
                    loser.name, winner.name,
                    quality_label(winner), quality_label(loser), sim
                ))
        else:
            keepers.append(f1)

        processed.add(f1)

    # Any files without fingerprints go through unchanged
    for f in files:
        if f not in fp_map and f not in processed:
            keepers.append(f)

    return keepers, rejected


# ---------------------------------------------------------------------------
# Tier 3: MusicBrainz confirmation
# ---------------------------------------------------------------------------

def _mb_confirm(candidates: list[Path], fp_map: dict) -> list[Path]:
    """
    Query AcoustID for each candidate. If all resolve to the same
    MusicBrainz recording ID, confirm as duplicates.
    If they resolve to DIFFERENT recordings, keep all (false positive).

    Returns the original list (confirmed duplicates) or just the first
    file if the match turns out to be a false positive.
    """
    recording_ids = {}

    for f in candidates:
        fp = fp_map.get(f)
        if not fp:
            continue
        try:
            # pyacoustid lookup
            results = acoustid.lookup(ACOUSTID_API_KEY, fp, 30.0,
                                      meta="recordings")
            for score, rid, title, artist in acoustid.parse_lookup_result(results):
                if score > 0.8:
                    recording_ids[f] = rid
                    dlog("TIER3: %s -> MB recording %s (score=%.2f)" % (
                        f.name, rid, score))
                    break
        except Exception as e:
            dlog("TIER3: AcoustID lookup failed for %s: %s" % (f.name, e))

    if not recording_ids:
        return candidates

    unique_ids = set(recording_ids.values())

    if len(unique_ids) == 1:
        # All same recording - confirmed duplicates
        dlog("TIER3: confirmed all %d files are same MB recording %s" % (
            len(candidates), list(unique_ids)[0]))
        return candidates
    else:
        # Different recordings - false positive, keep all
        dlog("TIER3: false positive - files are different recordings %s, keeping all" % unique_ids)
        return candidates[:1]  # Return only first to trigger keep-all path


# ---------------------------------------------------------------------------
# Rejection handling
# ---------------------------------------------------------------------------

def _move_to_rejected(path: Path, reason: str):
    """Move a rejected duplicate to the dedup_rejected staging area."""
    DEDUP_REJECTED_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    dst = DEDUP_REJECTED_DIR / ("%s_%s" % (timestamp, path.name))
    try:
        shutil.move(str(path), str(dst))
        dlog("MOVED TO REJECTED: %s (%s)" % (path.name, reason))
    except Exception as e:
        dlog("ERROR moving rejected file %s: %s" % (path.name, e))


# ---------------------------------------------------------------------------
# Size-aware chunking
# ---------------------------------------------------------------------------

def size_aware_chunks(album_groups: list, max_bytes: int = 4 * 1024 ** 3):
    """
    Pack album groups into chunks capped at max_bytes.
    Falls back to at least one album per chunk even if it exceeds the limit
    (can't split a single album across chunks).

    Each item in album_groups should be a Path (album directory) or a
    list of Paths (loose file group).
    """
    chunk = []
    chunk_bytes = 0

    for item in album_groups:
        # Estimate size
        if isinstance(item, Path):
            try:
                item_bytes = sum(
                    f.stat().st_size for f in item.rglob("*") if f.is_file()
                )
            except Exception:
                item_bytes = 50 * 1024 * 1024  # 50MB fallback
        elif isinstance(item, (list, tuple)):
            # Could be a list of files or (artist, album) tuple from group_files_by_album
            files = item if isinstance(item, list) else []
            item_bytes = sum(
                f.stat().st_size for f in files
                if isinstance(f, Path) and f.is_file()
            )
        else:
            item_bytes = 50 * 1024 * 1024

        # If adding this would exceed limit and we already have items, flush
        if chunk and chunk_bytes + item_bytes > max_bytes:
            yield chunk
            chunk = []
            chunk_bytes = 0

        chunk.append(item)
        chunk_bytes += item_bytes

    if chunk:
        yield chunk


# ---------------------------------------------------------------------------
# Main dedup entry point
# ---------------------------------------------------------------------------

def dedup_prelibrary(prelib: Path) -> dict:
    """
    Run full deduplication pass on all files currently in /pre-library.

    Walks all album directories, runs Tier 1 then Tier 2 on each group,
    moves losers to dedup_rejected.

    Returns stats dict with counts.
    """
    stats = {
        "albums_scanned": 0,
        "files_scanned": 0,
        "tier1_rejected": 0,
        "tier2_rejected": 0,
        "total_rejected": 0,
        "bytes_saved": 0,
    }

    if not prelib.exists():
        dlog("Pre-library does not exist: %s" % prelib)
        return stats

    dlog("=== Dedup pass starting on %s ===" % prelib)

    # Walk artist/album structure
    for artist_dir in sorted(prelib.iterdir()):
        if not artist_dir.is_dir():
            continue

        for album_dir in sorted(artist_dir.iterdir()):
            if not album_dir.is_dir():
                continue
            if "failed_imports" in album_dir.name:
                continue

            audio_files = [
                f for f in album_dir.rglob("*")
                if f.is_file() and f.suffix.lower() in AUDIO_EXTS
            ]

            if not audio_files:
                continue

            stats["albums_scanned"] += 1
            stats["files_scanned"] += len(audio_files)

            if len(audio_files) == 1:
                continue  # Nothing to dedup

            dlog("Album: %s/%s (%d files)" % (
                artist_dir.name, album_dir.name, len(audio_files)))

            # Tier 1: tag-based
            survivors, t1_rejected = tier1_dedup(audio_files)
            for rejected_path, kept_path, reason in t1_rejected:
                try:
                    bytes_saved = rejected_path.stat().st_size
                except Exception:
                    bytes_saved = 0
                _move_to_rejected(rejected_path, reason)
                stats["tier1_rejected"] += 1
                stats["bytes_saved"] += bytes_saved

            # Tier 2: fingerprint-based (only on survivors)
            if len(survivors) > 1:
                survivors, t2_rejected = tier2_dedup(survivors)
                for rejected_path, kept_path, reason in t2_rejected:
                    try:
                        bytes_saved = rejected_path.stat().st_size
                    except Exception:
                        bytes_saved = 0
                    _move_to_rejected(rejected_path, reason)
                    stats["tier2_rejected"] += 1
                    stats["bytes_saved"] += bytes_saved

    stats["total_rejected"] = stats["tier1_rejected"] + stats["tier2_rejected"]
    mb_saved = stats["bytes_saved"] / (1024 * 1024)

    dlog("=== Dedup complete: %d albums, %d files scanned, "
         "%d rejected (%d tier1, %d tier2), %.1fMB saved ===" % (
             stats["albums_scanned"],
             stats["files_scanned"],
             stats["total_rejected"],
             stats["tier1_rejected"],
             stats["tier2_rejected"],
             mb_saved,
         ))

    return stats
