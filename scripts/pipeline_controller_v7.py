#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v7.9 HYBRID Pipeline Controller

Changes from v7.8:
- Added PERMISSIONS_NEEDED_FLAG sentinel (/data/permissions_needed).
  fix_library_permissions() now only runs when new files were actually
  imported, skipping the expensive recursive find+chmod on runs where
  the inbox was empty or all artists were skipped. The sentinel is
  written by drain_prelibrary() after a successful import and cleared
  after fix_library_permissions() completes.
"""
import errno
import fcntl
import os
import subprocess
import sys
import traceback
from pathlib import Path
import time
import shutil

from scripts.pipeline.logging import log, update_status
from scripts.pipeline.locking import library_write_lock
from scripts.pipeline.slskd import artist_in_use, slskd_active_transfers
from scripts.pipeline.sabnzbd import sabnzbd_is_processing
from scripts.pipeline.settle import folder_is_settled
from scripts.pipeline.cleanup import cleanup_inbox_junk, cleanup_empty_inbox_tree
from scripts.pipeline.moves import (
    move_group_to_prelibrary,
    move_existing_album_folder_to_prelibrary,
    PreLibraryFullError,
)
from scripts.pipeline.metadata import group_files_by_album
from scripts.pipeline.beets import run_fingerprint, run_beets_import, run_post_import
from scripts.pipeline.system_hooks import (
    fix_library_permissions,
)
from scripts.pipeline.util import INBOX, PRELIB
from scripts.pipeline.quarantine import quarantine_failed_imports_global
from scripts.pipeline.regenerate import generate_ui_json


CHUNK_SIZE = 500
LOCK_FILE = Path("/data/pipeline.lock")

# Drain pre-library when it reaches this percentage of its budget.
# 85% gives enough headroom to move the next album before hitting the cap.
PRELIB_DRAIN_THRESHOLD = int(os.getenv("PRELIB_DRAIN_THRESHOLD", "85"))

# Size budget for /pre-library, in bytes.
#
# When /pre-library was a tmpfs, statvfs() on it returned the tmpfs's own
# size, so "percent full" was meaningful. On a normal directory (e.g. an NVMe
# bind mount) statvfs() returns the WHOLE FILESYSTEM's usage instead -- a 6 GB
# pre-library on a 916 GB disk reads as ~1% and never drains, while unrelated
# disk usage above 85% makes it drain constantly.
#
# So we measure the directory's own size against this budget. Set
# PRELIB_MAX_BYTES to match whatever the old tmpfs size= was.
PRELIB_MAX_BYTES = int(os.getenv("PRELIB_MAX_BYTES", str(6 * 1024**3)))

AUDIO_GLOBS = ["**/*.flac", "**/*.mp3", "**/*.m4a", "**/*.ogg", "**/*.wav", "**/*.aac"]

# Sentinel file written after any successful import. fix_library_permissions()
# only runs when this file exists, avoiding an expensive recursive find+chmod
# on runs where nothing was imported.
PERMISSIONS_NEEDED_FLAG = Path("/data/permissions_needed")


# ---------------------------------------------------------------------------
# tmpfs monitoring
# ---------------------------------------------------------------------------

def _is_tmpfs(path: Path) -> bool:
    """True if path sits on a tmpfs/ramfs mount."""
    try:
        target = os.path.realpath(str(path))
        with open("/proc/mounts") as f:
            best, fstype = "", ""
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                mnt, typ = parts[1], parts[2]
                if target == mnt or target.startswith(mnt.rstrip("/") + "/"):
                    if len(mnt) > len(best):
                        best, fstype = mnt, typ
        return fstype in ("tmpfs", "ramfs")
    except Exception:
        return False


def prelibrary_bytes_used() -> int:
    """Sum of file sizes under PRELIB, excluding failed_imports."""
    total = 0
    if not PRELIB.exists():
        return 0
    for root, dirs, files in os.walk(str(PRELIB)):
        if "failed_imports" in root.split(os.sep):
            continue
        dirs[:] = [d for d in dirs if d != "failed_imports"]
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def prelibrary_usage_pct() -> float:
    """
    Percentage of the pre-library budget currently used (0.0 - 100.0).

    On tmpfs, statvfs() describes the pre-library itself, so we use it -- it
    is a single cheap syscall. On any other filesystem statvfs() describes the
    whole disk, which is the wrong denominator entirely, so we walk the
    directory and compare against PRELIB_MAX_BYTES.

    Returns 0.0 if PRELIB doesn't exist or the check fails.
    """
    try:
        if not PRELIB.exists():
            return 0.0

        if _is_tmpfs(PRELIB):
            st = os.statvfs(str(PRELIB))
            total = st.f_blocks * st.f_frsize
            if total == 0:
                return 0.0
            used = total - (st.f_bfree * st.f_frsize)
            return (used / total) * 100.0

        if PRELIB_MAX_BYTES <= 0:
            return 0.0
        return (prelibrary_bytes_used() / PRELIB_MAX_BYTES) * 100.0

    except Exception as e:
        log("[PRELIB] Could not read pre-library usage: %s" % e)
        return 0.0


def log_prelibrary_usage():
    pct = prelibrary_usage_pct()
    mode = "tmpfs" if _is_tmpfs(PRELIB) else "dir/%dGB budget" % (PRELIB_MAX_BYTES // 1024**3)
    log("[PRELIB] Usage: %.1f%% (%s)" % (pct, mode))
    return pct


# ---------------------------------------------------------------------------
# Pre-library management
# ---------------------------------------------------------------------------

def clear_prelibrary():
    """
    Wipe /pre-library contents, skipping the failed_imports subfolder.
    Called inside drain_prelibrary() after each import cycle.
    """
    if not PRELIB.exists():
        return

    cleared = 0
    errors = 0

    for item in PRELIB.iterdir():
        if item.name == "failed_imports":
            log("[PRELIB] Skipping failed_imports (handled by quarantine)")
            continue
        try:
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
            cleared += 1
        except Exception as e:
            log("[PRELIB] Could not clear %s: %s" % (item.name, e))
            errors += 1

    if errors:
        log("[PRELIB] WARNING: %d items could not be cleared" % errors)

    log("[PRELIB] Pre-library cleared (%d items removed, %d errors)" % (cleared, errors))


def drain_prelibrary(reason: str = "startup"):
    """
    Import whatever is in pre-library right now, then wipe it.

    Sequence: quarantine failed_imports -> fingerprint -> import ->
              post-process -> clear -> verify.

    Called at pipeline startup (to drain leftovers from the previous run)
    and mid-run when tmpfs usage hits PRELIB_DRAIN_THRESHOLD or when a
    PreLibraryFullError is raised.

    Writes PERMISSIONS_NEEDED_FLAG after a successful import so
    fix_library_permissions() runs at end of pipeline.
    """
    pct = prelibrary_usage_pct()
    log("[DRAIN] Draining pre-library (%s, current usage %.1f%%)..." % (reason, pct))
    quarantine_failed_imports_global(PRELIB)
    run_fingerprint()
    run_beets_import()
    run_post_import()

    # Signal that new files were imported and need permissions fixed
    try:
        PERMISSIONS_NEEDED_FLAG.touch()
    except Exception as e:
        log("[DRAIN] Could not write permissions flag: %s" % e)

    clear_prelibrary()

    # Verify the clear actually worked
    survivors = [
        f for pattern in AUDIO_GLOBS
        for f in PRELIB.glob(pattern)
        if "failed_imports" not in str(f)
    ]
    if survivors:
        log("[DRAIN] WARNING: %d files survived clear_prelibrary() -- force removing:" % len(survivors))
        for f in survivors:
            log("[DRAIN]   %s" % f)
            try:
                f.unlink()
            except Exception as e:
                log("[DRAIN]   Could not remove %s: %s" % (f.name, e))
        # Remove any now-empty dirs left behind
        for item in list(PRELIB.iterdir()):
            if item.name == "failed_imports":
                continue
            if item.is_dir():
                try:
                    shutil.rmtree(item)
                except Exception as e:
                    log("[DRAIN]   Could not remove dir %s: %s" % (item.name, e))
    else:
        log("[DRAIN] Pre-library confirmed empty after clear")

    log("[DRAIN] Pre-library drained (%.1f%% -> %.1f%%)" % (pct, prelibrary_usage_pct()))


def maybe_drain_prelibrary(context: str = ""):
    """
    Check tmpfs usage and drain proactively if >= PRELIB_DRAIN_THRESHOLD.
    Call this before moving each album or group to pre-library.

    Returns True if a drain was triggered.
    """
    pct = prelibrary_usage_pct()
    if pct >= PRELIB_DRAIN_THRESHOLD:
        log("[PRELIB] Usage %.1f%% >= threshold %d%% ? draining before next move%s" % (
            pct, PRELIB_DRAIN_THRESHOLD,
            (" (%s)" % context) if context else "",
        ))
        drain_prelibrary("proactive threshold drain")
        return True
    return False


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------

class PipelineLock:
    """File-based lock to prevent concurrent pipeline runs."""

    def __init__(self, lockfile: Path = LOCK_FILE, timeout: int = 5):
        self.lockfile = lockfile
        self.timeout = timeout
        self.lock_fd = None

    def __enter__(self):
        log("[LOCK] Attempting to acquire lock: %s" % self.lockfile)
        self.lockfile.touch(exist_ok=True)
        self.lock_fd = open(self.lockfile, "a")

        start_time = time.time()
        while True:
            try:
                fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                log("[LOCK] Lock acquired successfully")
                return self
            except IOError:
                if time.time() - start_time >= self.timeout:
                    try:
                        check = subprocess.run(
                            ["pgrep", "-f", "pipeline_controller_v7.py"],
                            capture_output=True, text=True
                        )
                        pids = [p for p in check.stdout.strip().splitlines()
                                if p.strip() != str(os.getpid())]
                        if not pids:
                            log("[LOCK] Stale lock detected (no live process). Clearing.")
                            self.lock_fd.close()
                            self.lockfile.unlink(missing_ok=True)
                            self.lockfile.touch(exist_ok=True)
                            self.lock_fd = open(self.lockfile, "a")
                            start_time = time.time()
                            continue
                    except Exception as e:
                        log("[LOCK] Could not check for live process: %s" % e)

                    self.lock_fd.close()
                    log("[LOCK] ERROR: Could not acquire lock (another instance running?)")
                    raise RuntimeError(
                        "Pipeline is already running. "
                        "If this is incorrect, remove %s" % self.lockfile
                    )
                log("[LOCK] Waiting for lock...")
                time.sleep(1)

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.lock_fd:
            fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_UN)
            self.lock_fd.close()
            log("[LOCK] Lock released")
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def cleanup_invalid_failed_imports():
    invalid_locations = [Path("/inbox/failed_imports")]
    for path in invalid_locations:
        if not path.exists():
            continue
        log("[CLEANUP] Removing invalid failed_imports from: %s" % path)
        for root, dirs, files in os.walk(str(path)):
            for d in dirs:
                try:
                    os.chmod(os.path.join(root, d), 0o755)
                except Exception:
                    pass
            for f in files:
                try:
                    os.chmod(os.path.join(root, f), 0o644)
                except Exception as e:
                    log("[CLEANUP] Cannot chmod %s: %s -- attempting removal anyway" % (f, e))
        try:
            shutil.rmtree(path)
            log("[CLEANUP] Successfully removed: %s" % path)
        except Exception as e:
            log("[CLEANUP] Could not remove %s: %s" % (path, e))
            log("[CLEANUP] Fix manually: docker exec beetsV7 rm -rf /inbox/failed_imports")


def list_artist_folders():
    if not INBOX.exists():
        return []
    return [
        p for p in sorted(INBOX.iterdir())
        if p.is_dir()
        and not p.name.startswith("_UNPACK_")
        and p.name != "failed_imports"
    ]


AUDIO_DECODE_EXTS = {".flac", ".mp3", ".m4a", ".ogg", ".opus", ".wav", ".aac"}
CORRUPTION_CHECK_TIMEOUT = 120


def quick_corruption_check(filepath: Path) -> bool:
    """Return True if the file is intact.

    OLD BEHAVIOUR (bug): read the first 1024 bytes and returned True if at
    least 100 came back. That only proves a file exists and has a header. It
    cannot see damaged audio frames, which is precisely the corruption this
    pipeline produces -- 551 full-size FLACs with valid headers and shredded
    audio passed this check and were imported.

    NEW BEHAVIOUR: cheap structural checks first (existence, size, magic
    bytes), then an actual decode. For FLAC we use `flac -t`, which verifies
    the MD5 of the decoded audio stored in STREAMINFO -- it catches both
    truncation and mid-stream corruption. Falls back to ffmpeg for other
    formats, or if the flac binary is unavailable.
    """
    try:
        if not filepath.exists():
            log("[CORRUPT] Missing: %s" % filepath.name)
            return False

        size = filepath.stat().st_size
        if size < 4096:
            log("[CORRUPT] Too small (%d bytes): %s" % (size, filepath.name))
            return False

        ext = filepath.suffix.lower()
        if ext not in AUDIO_DECODE_EXTS:
            return True  # not ours to judge

        with open(filepath, "rb") as f:
            magic = f.read(4)
        if ext == ".flac" and magic != b"fLaC":
            log("[CORRUPT] Bad FLAC magic bytes: %s" % filepath.name)
            return False

        if ext == ".flac" and shutil.which("flac"):
            # -t: test. Verifies the STREAMINFO MD5 against decoded audio.
            cmd = ["flac", "-t", "--totally-silent", str(filepath)]
        elif shutil.which("ffmpeg"):
            cmd = ["ffmpeg", "-v", "error", "-i", str(filepath), "-f", "null", "-"]
        else:
            log("[CORRUPT] No flac/ffmpeg available; skipping deep check for %s"
                % filepath.name)
            return True

        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=CORRUPTION_CHECK_TIMEOUT)
        if result.returncode != 0 or result.stderr.strip():
            detail = (result.stderr or "").strip().splitlines()
            first = detail[0] if detail else "rc=%d" % result.returncode
            log("[CORRUPT] Decode failed for %s: %s" % (filepath.name, first))
            return False

        return True

    except subprocess.TimeoutExpired:
        log("[CORRUPT] Decode timed out (%ds): %s"
            % (CORRUPTION_CHECK_TIMEOUT, filepath.name))
        return False
    except Exception as e:
        log("[CORRUPT] Cannot read %s: %s" % (filepath.name, e))
        return False


def quarantine_corrupted_file(filepath: Path):
    from scripts.pipeline.quarantine import QUARANTINE_ROOT
    QUARANTINE_ROOT.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    dst = QUARANTINE_ROOT / ("corrupt_%s_%s" % (timestamp, filepath.name))
    log("[QUARANTINE] Corrupted file: %s" % filepath.name)
    try:
        shutil.move(str(filepath), str(dst))
    except Exception as e:
        log("[QUARANTINE] Failed to move %s: %s" % (filepath, e))


def chunk_list(items: list, chunk_size: int):
    for i in range(0, len(items), chunk_size):
        yield items[i:i + chunk_size]


# ---------------------------------------------------------------------------
# Core artist processing
# ---------------------------------------------------------------------------

def process_artist(artist_folder: Path, active_paths):
    """
    Process one artist folder through the full pipeline.

    Flow:
    1. Safety checks (SLSKD, SABnzbd, settle timer)
    2. Junk cleanup
    3. Collect loose files and album subfolders up front
    4. Move album subfolders to pre-library in chunks, import each chunk
       - Before each album move: check tmpfs usage, drain proactively at 85%
       - On ENOSPC (PreLibraryFullError): emergency drain then retry once
    5. Move loose file groups to pre-library in chunks, import each chunk
       - Same proactive and reactive ENOSPC handling
    6. Clean up empty inbox tree
    """
    if not artist_folder.exists():
        log("[SKIP] Folder disappeared before processing: %s" % artist_folder)
        return

    if artist_in_use(artist_folder, active_paths):
        log("[SKIP] SLSKD active match: %s" % artist_folder)
        return

    if sabnzbd_is_processing(artist_folder):
        log("[SKIP] SABnzbd still processing: %s" % artist_folder)
        return

    if not folder_is_settled(artist_folder, 300):
        log("[SKIP] Grace period not met: %s" % artist_folder)
        return

    log("ARTIST: %s" % artist_folder)
    update_status("running", "processing artist", artist_folder.name)

    try:
        cleanup_inbox_junk(artist_folder)
    except FileNotFoundError:
        log("[SKIP] Folder disappeared during cleanup: %s" % artist_folder)
        return

    if not artist_folder.exists():
        log("[SKIP] Folder removed during cleanup: %s" % artist_folder)
        return

    try:
        all_contents = list(artist_folder.iterdir())
    except FileNotFoundError:
        log("[SKIP] Folder disappeared while listing contents: %s" % artist_folder)
        return

    loose_audio = [
        p for p in all_contents
        if p.is_file()
        and p.suffix.lower() in {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aac"}
    ]

    albums_to_process = []
    for sub in sorted(p for p in all_contents if p.is_dir()):
        try:
            if sub.name == "failed_imports":
                continue
        except FileNotFoundError:
            continue

        if not folder_is_settled(sub, 300):
            log("[SKIP] Album subfolder not settled: %s" % sub)
            continue

        try:
            audio_files = [
                f for f in sub.rglob("*")
                if f.is_file()
                and f.suffix.lower() in {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aac"}
            ]
        except (FileNotFoundError, PermissionError):
            log("[SKIP] Cannot access subfolder: %s" % sub)
            continue

        corrupted_count = 0
        for audio_file in audio_files:
            if not quick_corruption_check(audio_file):
                quarantine_corrupted_file(audio_file)
                corrupted_count += 1

        try:
            remaining = [
                f for f in sub.rglob("*")
                if f.is_file()
                and f.suffix.lower() in {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aac"}
            ]
        except (FileNotFoundError, PermissionError):
            log("[SKIP] Folder disappeared during corruption check: %s" % sub)
            continue

        if remaining:
            if corrupted_count > 0:
                log("[VALIDATE] Removed %d corrupted files from %s" % (corrupted_count, sub.name))
            albums_to_process.append(sub)
        else:
            log("[SKIP] No valid files remaining in %s" % sub.name)

    # --- Process album subfolders in chunks ---
    if albums_to_process:
        total_albums = len(albums_to_process)
        log("[CHUNK] Processing %d albums in chunks of %d" % (total_albums, CHUNK_SIZE))

        chunks = list(chunk_list(albums_to_process, CHUNK_SIZE))
        for chunk_idx, album_chunk in enumerate(chunks, 1):
            log("[CHUNK] Album chunk %d/%d (%d albums)" % (chunk_idx, len(chunks), len(album_chunk)))

            for album in album_chunk:
                # Proactive: drain before the move if tmpfs is getting full
                maybe_drain_prelibrary(album.name)

                try:
                    move_existing_album_folder_to_prelibrary(album)
                except FileNotFoundError:
                    log("[SKIP] Album folder disappeared: %s" % album)
                except PreLibraryFullError:
                    # Reactive: ENOSPC despite proactive check (album was huge)
                    log("[ENOSPC] Emergency drain triggered by: %s" % album.name)
                    drain_prelibrary("emergency ENOSPC")
                    try:
                        move_existing_album_folder_to_prelibrary(album)
                    except (PreLibraryFullError, Exception) as retry_err:
                        log("[ENOSPC] Retry failed for %s: %s ? skipping" % (album.name, retry_err))

            log("[CHUNK] Fingerprinting chunk %d" % chunk_idx)
            run_fingerprint()

            log("[CHUNK] Importing chunk %d" % chunk_idx)
            run_beets_import()

            log("[CHUNK] Post-processing chunk %d" % chunk_idx)
            run_post_import()

            if chunk_idx < len(chunks):
                log("[CHUNK] Waiting 2s before next chunk...")
                time.sleep(2)

    # --- Process loose audio files in chunks ---
    if loose_audio:
        valid_audio = []
        for audio_file in loose_audio:
            if audio_file.exists():
                if quick_corruption_check(audio_file):
                    valid_audio.append(audio_file)
                else:
                    quarantine_corrupted_file(audio_file)

        if valid_audio:
            groups = group_files_by_album(valid_audio)
            group_items = list(groups.items())
            total_groups = len(group_items)

            log("[CHUNK] Processing %d loose file groups in chunks of %d" % (total_groups, CHUNK_SIZE))

            chunks = list(chunk_list(group_items, CHUNK_SIZE))
            for chunk_idx, group_chunk in enumerate(chunks, 1):
                log("[CHUNK] Loose chunk %d/%d (%d groups)" % (chunk_idx, len(chunks), len(group_chunk)))

                for (aa, al), files in group_chunk:
                    # Proactive: drain before move if tmpfs is getting full
                    maybe_drain_prelibrary("%s/%s" % (aa, al))

                    try:
                        move_group_to_prelibrary(
                            aa or artist_folder.name,
                            al or "Unknown Album",
                            files,
                        )
                    except PreLibraryFullError:
                        log("[ENOSPC] Emergency drain triggered by loose group: %s/%s" % (aa, al))
                        drain_prelibrary("emergency ENOSPC")
                        try:
                            move_group_to_prelibrary(
                                aa or artist_folder.name,
                                al or "Unknown Album",
                                files,
                            )
                        except (PreLibraryFullError, Exception) as retry_err:
                            log("[ENOSPC] Retry failed for %s/%s: %s ? skipping" % (aa, al, retry_err))

                log("[CHUNK] Fingerprinting loose chunk %d" % chunk_idx)
                run_fingerprint()

                log("[CHUNK] Importing loose chunk %d" % chunk_idx)
                run_beets_import()

                log("[CHUNK] Post-processing loose chunk %d" % chunk_idx)
                run_post_import()

                if chunk_idx < len(chunks):
                    log("[CHUNK] Waiting 2s before next chunk...")
                    time.sleep(2)

    # Cleanup empty inbox tree
    try:
        if artist_folder.exists() and not any(artist_folder.iterdir()):
            cleanup_empty_inbox_tree(artist_folder)
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    try:
        # PipelineLock stops two pipeline runs overlapping.
        # library_write_lock stops the pipeline overlapping with
        # watch_metadata.py or beets_metadata_refresh.py. All three run `beet`
        # commands that rewrite audio files, and two concurrent rewrites of one
        # FLAC shred it. Blocking here rather than skipping: a pipeline run
        # that waits a few minutes is fine; one that runs alongside the 03:00
        # metadata refresh is how 1,002 files died.
        with PipelineLock(timeout=5), library_write_lock("pipeline_controller"):
            log("=== v8.0 Hybrid Pipeline Controller ===")
            update_status("running", "starting pipeline")

            cleanup_invalid_failed_imports()

            # Drain pre-library at startup: give leftover files from the
            # previous run one more import attempt before clearing.
            log("[PRELIB] Draining pre-library leftovers before new run...")
            drain_prelibrary("startup")

            log("[SLSKD] Fetching active transfers (non-blocking)...")
            active_paths_initial = slskd_active_transfers()
            if active_paths_initial:
                log("[SLSKD] %d active/queued transfers -- will skip matching artists, process the rest" % len(active_paths_initial))
            else:
                log("[SLSKD] No active transfers")

            artists = list_artist_folders()

            if not artists:
                log("Inbox empty - nothing to do.")
                update_status("idle", "inbox empty")
                return

            for artist in artists:
                if not artist.exists():
                    log("[SKIP] Artist folder disappeared: %s" % artist)
                    continue

                active_paths = slskd_active_transfers()

                try:
                    process_artist(artist, active_paths)
                except FileNotFoundError as e:
                    log("[SKIP] Folder disappeared during processing: %s - %s" % (artist, e))
                except Exception as e:
                    log("[ERROR] Error processing %s: %s" % (artist, e))
                    log("[ERROR] Traceback: %s" % traceback.format_exc())

            time.sleep(2)

            # Only run expensive permission fix if new files were imported
            if PERMISSIONS_NEEDED_FLAG.exists():
                fix_library_permissions()
                try:
                    PERMISSIONS_NEEDED_FLAG.unlink(missing_ok=True)
                except Exception as e:
                    log("[PERMISSIONS] Could not remove flag: %s" % e)
            else:
                log("[PERMISSIONS] No new imports -- skipping permission fix")

            generate_ui_json()

            log("=== v7.9 Pipeline Finished ===")
            update_status("success", "pipeline finished")

    except RuntimeError as e:
        log("[ERROR] %s" % e)
        update_status("error", str(e))
        sys.exit(1)
    except Exception as e:
        log("[ERROR] Pipeline failed: %s" % e)
        update_status("error", "pipeline failed: %s" % e)
        log("[ERROR] Traceback: %s" % traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
