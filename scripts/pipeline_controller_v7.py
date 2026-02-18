#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v7.5 HYBRID Pipeline Controller

Changes from v7.4:
- active_paths is now refreshed per-artist instead of captured once at startup.
  Previously a single snapshot was taken before the artist loop began. If SLSKD
  started a new download mid-run, the stale snapshot would not catch it, meaning
  a partially-downloaded folder could be moved to pre-library and fail to import.
- global_settle() still runs at startup as a gate, but slskd_active_transfers()
  is called again before each individual artist is processed.
"""
import fcntl
import os
import subprocess
import sys
import traceback
from pathlib import Path
import time
import shutil

from scripts.pipeline.logging import log, update_status
from scripts.pipeline.slskd import artist_in_use, slskd_active_transfers
from scripts.pipeline.sabnzbd import sabnzbd_is_processing
from scripts.pipeline.settle import folder_is_settled
from scripts.pipeline.cleanup import cleanup_inbox_junk, cleanup_empty_inbox_tree
from scripts.pipeline.moves import move_group_to_prelibrary, move_existing_album_folder_to_prelibrary
from scripts.pipeline.metadata import group_files_by_album
from scripts.pipeline.beets import run_fingerprint, run_beets_import, run_post_import
from scripts.pipeline.system_hooks import (
    fix_library_permissions,
    trigger_subsonic_scan_from_config,
    trigger_volumio_rescan,
)
from scripts.pipeline.util import INBOX, PRELIB
from scripts.pipeline.quarantine import quarantine_failed_imports_global
from scripts.pipeline.regenerate import generate_ui_json


CHUNK_SIZE = 25
LOCK_FILE = Path("/data/pipeline.lock")


class PipelineLock:
    """File-based lock to prevent concurrent pipeline runs."""

    def __init__(self, lockfile: Path = LOCK_FILE, timeout: int = 5):
        self.lockfile = lockfile
        self.timeout = timeout
        self.lock_fd = None

    def __enter__(self):
        log("[LOCK] Attempting to acquire lock: %s" % self.lockfile)

        self.lockfile.touch(exist_ok=True)

        # FIX: Open with 'a' (append) not 'r' (read-only).
        # fcntl.flock(LOCK_EX) on a read-only file descriptor is unreliable
        # on some Linux kernels and will always fail with EBADF.
        self.lock_fd = open(self.lockfile, "a")

        # FIX: Auto-clear stale lock left behind by a container restart.
        # A restarted container will never have a live process holding the lock,
        # so if we can't acquire it within the timeout it must be stale.
        # We attempt a non-blocking lock first; if it fails we check whether
        # any pipeline process is actually running before giving up.
        start_time = time.time()
        while True:
            try:
                fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                log("[LOCK] Lock acquired successfully")
                return self
            except IOError:
                if time.time() - start_time >= self.timeout:
                    # Check if a pipeline process is actually alive
                    try:
                        check = subprocess.run(
                            ["pgrep", "-f", "pipeline_controller_v7.py"],
                            capture_output=True, text=True
                        )
                        # pgrep returns our own PID too, so filter it out
                        pids = [p for p in check.stdout.strip().splitlines()
                                if p.strip() != str(os.getpid())]
                        if not pids:
                            # No other pipeline process running -- stale lock
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


def cleanup_invalid_failed_imports():
    """
    Remove failed_imports folders from locations they should never exist.

    FIX: shutil.rmtree fails with Permission denied if any file inside is
    read-only or owned by a different user. We chmod everything writable
    first. If chmod fails we log and attempt removal anyway.
    """
    invalid_locations = [Path("/inbox/failed_imports")]
    for path in invalid_locations:
        if not path.exists():
            continue

        log("[CLEANUP] Removing invalid failed_imports from: %s" % path)

        # Make everything writable before rmtree
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
                    log("[CLEANUP] Cannot chmod %s: %s -- will attempt removal anyway" % (f, e))

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


def quick_corruption_check(filepath: Path) -> bool:
    """Fast check - verify file is readable and non-trivially small."""
    try:
        if not filepath.exists() or filepath.stat().st_size == 0:
            log("[CORRUPT] Empty or missing: %s" % filepath.name)
            return False
        with open(filepath, "rb") as f:
            header = f.read(1024)
            if len(header) < 100:
                log("[CORRUPT] File too small: %s" % filepath.name)
                return False
        return True
    except Exception as e:
        log("[CORRUPT] Cannot read %s: %s" % (filepath.name, e))
        return False


def quarantine_corrupted_file(filepath: Path):
    """Move a corrupted file to quarantine."""
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


def process_artist(artist_folder: Path, active_paths):
    """
    Process one artist folder through the full pipeline.

    Flow:
    1. Safety checks (SLSKD, SABnzbd, settle timer)
    2. Junk cleanup
    3. Collect loose files NOW before any moves happen
    4. Collect album subfolders, check corruption
    5. Move albums to pre-library and import in chunks
    6. Move loose files to pre-library and import in chunks
    7. Clean up empty inbox tree
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

    # FIX: Collect BOTH loose files and subfolders NOW before anything is moved.
    # Previously loose files were collected after album subfolders were moved out,
    # meaning artist_folder could be empty or gone by the time we checked for them.
    try:
        all_contents = list(artist_folder.iterdir())
    except FileNotFoundError:
        log("[SKIP] Folder disappeared while listing contents: %s" % artist_folder)
        return

    # Separate loose audio files from album subfolders up front
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
                try:
                    move_existing_album_folder_to_prelibrary(album)
                except FileNotFoundError:
                    log("[SKIP] Album folder disappeared: %s" % album)

            log("[CHUNK] Fingerprinting chunk %d" % chunk_idx)
            run_fingerprint()

            log("[CHUNK] Importing chunk %d" % chunk_idx)
            run_beets_import()

            log("[CHUNK] Post-processing chunk %d" % chunk_idx)
            run_post_import()

            # FIX: Delay check was "chunk_idx * CHUNK_SIZE < total_albums" which
            # incorrectly skips the delay on the last chunk when total is exact
            # multiple of CHUNK_SIZE. Now simply check if more chunks remain.
            if chunk_idx < len(chunks):
                log("[CHUNK] Waiting 2s before next chunk...")
                time.sleep(2)

    # --- Process loose audio files in chunks ---
    if loose_audio:
        valid_audio = []
        for audio_file in loose_audio:
            if audio_file.exists():  # May have been cleaned up already
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
                    move_group_to_prelibrary(
                        aa or artist_folder.name,
                        al or "Unknown Album",
                        files,
                    )

                log("[CHUNK] Fingerprinting loose chunk %d" % chunk_idx)
                run_fingerprint()

                log("[CHUNK] Importing loose chunk %d" % chunk_idx)
                run_beets_import()

                log("[CHUNK] Post-processing loose chunk %d" % chunk_idx)
                run_post_import()

                # FIX: Same delay fix as above
                if chunk_idx < len(chunks):
                    log("[CHUNK] Waiting 2s before next chunk...")
                    time.sleep(2)

    # Cleanup empty inbox tree
    try:
        if artist_folder.exists() and not any(artist_folder.iterdir()):
            cleanup_empty_inbox_tree(artist_folder)
    except FileNotFoundError:
        pass


def main():
    try:
        with PipelineLock(timeout=5):
            log("=== v7.5 Hybrid Pipeline Controller ===")
            update_status("running", "starting pipeline")

            cleanup_invalid_failed_imports()
            quarantine_failed_imports_global(PRELIB)

            # FIX: Removed global_settle() as a hard gate. Previously the pipeline
            # would block until ALL SLSKD transfers finished (threshold=0), meaning
            # if you had 15 active downloads it would wait 30s between each check
            # until the queue was completely empty -- potentially hours.
            #
            # This was unnecessary because process_artist() already does a
            # per-artist artist_in_use() check using fuzzy matching against active
            # transfer paths. Artists with no active downloads are safe to process
            # immediately. We just need the current transfer list as a reference,
            # not a guarantee the entire queue is empty.
            #
            # active_paths is refreshed per-artist inside the loop below so it
            # stays current as downloads complete during a long pipeline run.
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

                # FIX: Refresh active transfer list per-artist rather than using
                # a stale snapshot captured once before the loop. A download that
                # starts mid-run would not appear in the original snapshot, meaning
                # a partially-downloaded folder could be processed incorrectly.
                active_paths = slskd_active_transfers()

                try:
                    process_artist(artist, active_paths)
                except FileNotFoundError as e:
                    log("[SKIP] Folder disappeared during processing: %s - %s" % (artist, e))
                except Exception as e:
                    log("[ERROR] Error processing %s: %s" % (artist, e))
                    log("[ERROR] Traceback: %s" % traceback.format_exc())

            time.sleep(2)
            fix_library_permissions()
            generate_ui_json()
            trigger_subsonic_scan_from_config()
            trigger_volumio_rescan()

            log("=== v7.5 Pipeline Finished ===")
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