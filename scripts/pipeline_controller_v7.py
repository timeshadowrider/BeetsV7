#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import time

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


def list_artist_folders():
    if not INBOX.exists():
        return []
    return [
        p for p in sorted(INBOX.iterdir())
        if p.is_dir()
        and not p.name.startswith("_UNPACK_")
        and p.name != "failed_imports"
    ]


def process_artist(artist_folder: Path, active_paths):
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

    # Move album subfolders
    for sub in sorted(artist_folder.iterdir()):
        if sub.is_dir() and sub.name != "failed_imports":
            if folder_is_settled(sub, 3600):
                move_existing_album_folder_to_prelibrary(sub)
            else:
                log("[SKIP] Album subfolder not settled: %s" % sub)

    # Loose files
    loose = [p for p in artist_folder.iterdir() if p.is_file()]
    audio = [
        p for p in loose
        if p.suffix.lower() in {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aac"}
    ]

    if audio:
        groups = group_files_by_album(audio)
        for (aa, al), files in groups.items():
            move_group_to_prelibrary(
                aa or artist_folder.name,
                al or "Unknown Album",
                files,
            )
            run_fingerprint()
            run_beets_import()
            run_post_import()

    # Cleanup empty inbox tree
    try:
        if not any(artist_folder.iterdir()):
            cleanup_empty_inbox_tree(artist_folder)
    except FileNotFoundError:
        pass


def main():
    log("=== v7.3 Modular Pipeline Controller ===")
    update_status("running", "starting pipeline")

    # Always quarantine from the correct root
    quarantine_root = Path("/music/quarantine/failed_imports")
    quarantine_root.mkdir(parents=True, exist_ok=True)
    quarantine_failed_imports_global(quarantine_root)

    active_paths = global_settle()

    artists = list_artist_folders()
    if not artists:
        log("Inbox empty - nothing to do.")
        update_status("idle", "inbox empty")
        return

    for artist in artists:
        process_artist(artist, active_paths)

    # FIX: ensure filesystem settles before UI generation
    time.sleep(2)

    # FIX: run permissions BEFORE UI generation
    fix_library_permissions()

    # FIX: generate UI JSON only after library is stable
    generate_ui_json()

    trigger_subsonic_scan_from_config()
    trigger_volumio_rescan()

    log("=== v7.3 Pipeline Finished ===")
    update_status("success", "pipeline finished")


if __name__ == "__main__":
    main()
