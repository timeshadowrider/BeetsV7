#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v7.3 HYBRID Pipeline Controller (FINAL)

Features:
- File-based locking (prevents concurrent runs)
- Chunked processing (25 files at a time)
- Quick corruption check in /inbox
- Beets handles heavy metadata validation
- Failed imports quarantined automatically
"""
import fcntl
import sys
from pathlib import Path
import time
import shutil
from scripts.pipeline.logging import log, update_status
from scripts.pipeline.slskd import global_settle, artist_in_use
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


# Configuration
CHUNK_SIZE = 25  # Process files in batches of 25
LOCK_FILE = Path("/data/pipeline.lock")  # In /data so it's accessible outside container


class PipelineLock:
    """
    File-based lock to prevent concurrent pipeline runs.
    
    Usage:
        with PipelineLock():
            # Pipeline code here
            # Lock is automatically released on exit
    """
    def __init__(self, lockfile: Path = LOCK_FILE, timeout: int = 5):
        self.lockfile = lockfile
        self.timeout = timeout
        self.lock_fd = None
    
    def __enter__(self):
        """Acquire the lock"""
        log(f"[LOCK] Attempting to acquire lock: {self.lockfile}")
        
        # Create lock file if it doesn't exist
        self.lockfile.touch(exist_ok=True)
        
        # Open lock file
        self.lock_fd = open(self.lockfile, 'r')
        
        # Try to acquire exclusive lock with timeout
        start_time = time.time()
        while True:
            try:
                fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                log("[LOCK] Lock acquired successfully")
                return self
            except IOError:
                if time.time() - start_time >= self.timeout:
                    log("[LOCK] ERROR: Could not acquire lock (another instance running?)")
                    raise RuntimeError(
                        "Pipeline is already running. "
                        f"If this is incorrect, remove {self.lockfile}"
                    )
                log("[LOCK] Waiting for lock (another instance running)...")
                time.sleep(1)
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Release the lock"""
        if self.lock_fd:
            fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_UN)
            self.lock_fd.close()
            log("[LOCK] Lock released")
        
        # Don't delete lock file - keep it for next run
        return False  # Don't suppress exceptions


def cleanup_invalid_failed_imports():
    """Remove failed_imports folders from invalid locations"""
    invalid_locations = [Path("/inbox/failed_imports")]
    
    for path in invalid_locations:
        if path.exists():
            log(f"[CLEANUP] Removing invalid failed_imports from: {path}")
            try:
                shutil.rmtree(path)
                log(f"[CLEANUP] Successfully removed: {path}")
            except Exception as e:
                log(f"[CLEANUP] Could not remove {path}: {e}")


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
    """
    Fast corruption check - verify file is readable and non-zero.
    Catches obviously broken files without deep validation.
    """
    try:
        # Check file exists and has size
        if not filepath.exists() or filepath.stat().st_size == 0:
            log(f"[CORRUPT] Empty or missing: {filepath.name}")
            return False
        
        # Try to open and read first few bytes
        with open(filepath, 'rb') as f:
            header = f.read(1024)
            if len(header) < 100:
                log(f"[CORRUPT] File too small: {filepath.name}")
                return False
        
        return True
        
    except Exception as e:
        log(f"[CORRUPT] Cannot read {filepath.name}: {e}")
        return False


def quarantine_corrupted_file(filepath: Path):
    """Move obviously corrupted file to quarantine"""
    from scripts.pipeline.quarantine import QUARANTINE_ROOT
    
    QUARANTINE_ROOT.mkdir(parents=True, exist_ok=True)
    
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    safe_name = f"corrupt_{timestamp}_{filepath.name}"
    dst = QUARANTINE_ROOT / safe_name
    
    log(f"[QUARANTINE] Corrupted file: {filepath.name}")
    
    try:
        shutil.move(str(filepath), str(dst))
    except Exception as e:
        log(f"[QUARANTINE] Failed to move {filepath}: {e}")


def chunk_list(items: list, chunk_size: int):
    """
    Split a list into chunks of specified size.
    
    Example:
        chunk_list([1,2,3,4,5], 2) -> [[1,2], [3,4], [5]]
    """
    for i in range(0, len(items), chunk_size):
        yield items[i:i + chunk_size]


def process_artist(artist_folder: Path, active_paths):
    """
    Process artist folder with hybrid approach + chunking.
    
    Flow:
    1. Quick corruption check in /inbox
    2. Move valid files to /pre-library
    3. Process in chunks of CHUNK_SIZE files
    4. Beets handles metadata validation per chunk
    """
    if artist_in_use(artist_folder, active_paths):
        log("[SKIP] SLSKD soft-busy match: %s" % artist_folder)
        return
    
    if sabnzbd_is_processing(artist_folder):
        log("[SKIP] SABnzbd still processing: %s" % artist_folder)
        return
    
    if not folder_is_settled(artist_folder, 300):
        log("[SKIP] Grace period not met: %s" % artist_folder)
        return
    
    log("ARTIST: %s" % artist_folder)
    update_status("running", "processing artist", artist_folder.name)
    
    cleanup_inbox_junk(artist_folder)
    
    # Track all albums to process (for chunking)
    albums_to_process = []
    
    # Process album subfolders
    for sub in sorted(artist_folder.iterdir()):
        if not sub.is_dir() or sub.name == "failed_imports":
            continue
            
        if not folder_is_settled(sub, 3600):
            log("[SKIP] Album subfolder not settled: %s" % sub)
            continue
        
        # Quick corruption check for audio files in the folder
        audio_files = [
            f for f in sub.rglob("*")
            if f.is_file() and f.suffix.lower() in {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aac"}
        ]
        
        corrupted_count = 0
        for audio_file in audio_files:
            if not quick_corruption_check(audio_file):
                quarantine_corrupted_file(audio_file)
                corrupted_count += 1
        
        # If folder still has files after corruption check, mark for processing
        remaining_files = [
            f for f in sub.rglob("*")
            if f.is_file() and f.suffix.lower() in {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aac"}
        ]
        
        if remaining_files:
            if corrupted_count > 0:
                log(f"[VALIDATE] Removed {corrupted_count} corrupted files from {sub.name}")
            albums_to_process.append(sub)
        else:
            log(f"[SKIP] No valid files remaining in {sub.name}")
    
    # Process albums in chunks
    if albums_to_process:
        total_albums = len(albums_to_process)
        log(f"[CHUNK] Processing {total_albums} albums in chunks of {CHUNK_SIZE}")
        
        for chunk_idx, album_chunk in enumerate(chunk_list(albums_to_process, CHUNK_SIZE), 1):
            log(f"[CHUNK] Processing chunk {chunk_idx} ({len(album_chunk)} albums)")
            
            # Move this chunk to pre-library
            for album in album_chunk:
                move_existing_album_folder_to_prelibrary(album)
            
            # Process this chunk with Beets
            log(f"[CHUNK] Fingerprinting chunk {chunk_idx}")
            run_fingerprint()
            
            log(f"[CHUNK] Importing chunk {chunk_idx}")
            run_beets_import()
            
            log(f"[CHUNK] Post-processing chunk {chunk_idx}")
            run_post_import()
            
            # Small delay between chunks to avoid overwhelming the system
            if chunk_idx * CHUNK_SIZE < total_albums:
                log(f"[CHUNK] Waiting 2s before next chunk...")
                time.sleep(2)
    
    # Process loose files (also chunked)
    loose = [p for p in artist_folder.iterdir() if p.is_file()]
    audio = [
        p for p in loose
        if p.suffix.lower() in {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aac"}
    ]
    
    if audio:
        # Quick corruption check
        valid_audio = []
        for audio_file in audio:
            if quick_corruption_check(audio_file):
                valid_audio.append(audio_file)
            else:
                quarantine_corrupted_file(audio_file)
        
        if valid_audio:
            # Group by album
            groups = group_files_by_album(valid_audio)
            
            # Process groups in chunks
            group_items = list(groups.items())
            total_groups = len(group_items)
            
            if total_groups > 0:
                log(f"[CHUNK] Processing {total_groups} loose file groups in chunks of {CHUNK_SIZE}")
                
                for chunk_idx, group_chunk in enumerate(chunk_list(group_items, CHUNK_SIZE), 1):
                    log(f"[CHUNK] Processing loose files chunk {chunk_idx} ({len(group_chunk)} groups)")
                    
                    # Move this chunk to pre-library
                    for (aa, al), files in group_chunk:
                        move_group_to_prelibrary(
                            aa or artist_folder.name,
                            al or "Unknown Album",
                            files,
                        )
                    
                    # Process this chunk with Beets
                    log(f"[CHUNK] Fingerprinting loose files chunk {chunk_idx}")
                    run_fingerprint()
                    
                    log(f"[CHUNK] Importing loose files chunk {chunk_idx}")
                    run_beets_import()
                    
                    log(f"[CHUNK] Post-processing loose files chunk {chunk_idx}")
                    run_post_import()
                    
                    # Delay between chunks
                    if chunk_idx * CHUNK_SIZE < total_groups:
                        log(f"[CHUNK] Waiting 2s before next chunk...")
                        time.sleep(2)
    
    # Cleanup empty inbox tree
    try:
        if not any(artist_folder.iterdir()):
            cleanup_empty_inbox_tree(artist_folder)
    except FileNotFoundError:
        pass


def main():
    """
    Main pipeline execution with locking.
    
    The lock ensures only one instance runs at a time.
    """
    try:
        with PipelineLock(timeout=5):
            log("=== v7.3 Hybrid Pipeline Controller (FINAL) ===")
            update_status("running", "starting pipeline")
            
            # Clean up invalid failed_imports folders
            cleanup_invalid_failed_imports()
            
            # Quarantine any failed imports from pre-library
            quarantine_failed_imports_global(PRELIB)
            
            active_paths = global_settle()
            artists = list_artist_folders()
            
            if not artists:
                log("Inbox empty - nothing to do.")
                update_status("idle", "inbox empty")
                return
            
            # Process all artists (chunked processing happens inside)
            for artist in artists:
                process_artist(artist, active_paths)
            
            # Final cleanup and notifications
            time.sleep(2)
            fix_library_permissions()
            generate_ui_json()
            trigger_subsonic_scan_from_config()
            trigger_volumio_rescan()
            
            log("=== v7.3 Pipeline Finished ===")
            update_status("success", "pipeline finished")
            
    except RuntimeError as e:
        log(f"[ERROR] {e}")
        update_status("error", str(e))
        sys.exit(1)
    except Exception as e:
        log(f"[ERROR] Pipeline failed: {e}")
        update_status("error", f"pipeline failed: {e}")
        raise


if __name__ == "__main__":
    main()