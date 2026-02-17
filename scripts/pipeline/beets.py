#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Beets Integration Module - v7 (CORRECTED)

Fixed Issues:
- Post-import updates look in /music/library (not /pre-library)
- Proper error handling and logging
- Files should move from /pre-library to /music/library
"""
from .util import run, PRELIB, LIBRARY
from .logging import vlog, log
from pathlib import Path


def run_fingerprint():
    """Run AcoustID fingerprinting on all files in /pre-library"""
    vlog("[FP] Running fingerprint pass...")
    
    # Check if there are files to fingerprint
    if not PRELIB.exists() or not any(PRELIB.iterdir()):
        vlog("[FP] No files in /pre-library to fingerprint")
        return
    
    try:
        run(["python3", "/app/scripts/fingerprint_all.py"])
        vlog("[FP] Fingerprinting completed")
    except Exception as e:
        log(f"[FP] Warning: Fingerprinting failed: {e}")


def run_beets_import():
    """
    Import files from /pre-library to /music/library.
    
    With move: yes in config.yaml, files will be:
    1. Matched against MusicBrainz
    2. Tagged with metadata
    3. MOVED to /music/library
    4. Removed from /pre-library
    
    Failed imports stay in /pre-library/failed_imports
    """
    vlog("[BEETS] Importing pre-library...")
    
    # Check if there are files to import
    if not PRELIB.exists() or not any(PRELIB.iterdir()):
        vlog("[BEETS] No files in /pre-library to import")
        return
    
    try:
        # Import from /pre-library
        # Files will be moved to /music/library based on config.yaml
        run(["beet", "import", "-q", str(PRELIB)])
        vlog("[BEETS] Import completed")
        
        # Verify files moved
        remaining = list(PRELIB.glob("**/*.flac")) + list(PRELIB.glob("**/*.mp3"))
        # Filter out failed_imports directory
        remaining = [f for f in remaining if "failed_imports" not in str(f)]
        
        if remaining:
            log(f"[BEETS] Warning: {len(remaining)} files still in /pre-library after import")
            # These might be files that couldn't be matched
        else:
            vlog("[BEETS] All files successfully moved from /pre-library")
            
    except Exception as e:
        log(f"[BEETS] Import error: {e}")


def run_post_import():
    """
    Post-import cleanup and updates.
    
    CRITICAL FIX: After import with move:yes, files are in /music/library,
    NOT in /pre-library anymore. So we update files in the library location.
    """
    vlog("[BEETS] Post-import update/move...")
    
    try:
        # Update metadata for files that were just imported
        # Look for recently added files (within last hour)
        vlog("[BEETS] Updating recently imported files...")
        run(["beet", "update", "added:-1h.."])
        
        # Ensure any files that should be moved are moved
        # This catches files that may have been imported but not moved
        vlog("[BEETS] Ensuring files are in correct location...")
        run(["beet", "move"])
        
        # Final update pass on the entire library
        # This ensures all tags are written
        vlog("[BEETS] Final metadata update...")
        run(["beet", "update", "path:%s" % LIBRARY])
        
        vlog("[BEETS] Post-import completed")
        
    except Exception as e:
        log(f"[BEETS] Post-import warning: {e}")


def verify_import_success():
    """
    Verify that files successfully moved from /pre-library to /music/library.
    
    Returns:
        dict: Statistics about the import
    """
    stats = {
        "prelib_remaining": 0,
        "library_total": 0,
        "failed_imports": 0
    }
    
    # Count files still in /pre-library (excluding failed_imports)
    if PRELIB.exists():
        for ext in ["*.flac", "*.mp3", "*.m4a"]:
            files = list(PRELIB.glob(f"**/{ext}"))
            files = [f for f in files if "failed_imports" not in str(f)]
            stats["prelib_remaining"] += len(files)
    
    # Count files in /music/library
    if LIBRARY.exists():
        for ext in ["*.flac", "*.mp3", "*.m4a"]:
            stats["library_total"] += len(list(LIBRARY.glob(f"**/{ext}")))
    
    # Count failed imports
    failed_dir = PRELIB / "failed_imports"
    if failed_dir.exists():
        for ext in ["*.flac", "*.mp3", "*.m4a"]:
            stats["failed_imports"] += len(list(failed_dir.glob(f"**/{ext}")))
    
    # Log results
    log(f"[VERIFY] Import Statistics:")
    log(f"[VERIFY]   Library: {stats['library_total']} files")
    log(f"[VERIFY]   Pre-library remaining: {stats['prelib_remaining']} files")
    log(f"[VERIFY]   Failed imports: {stats['failed_imports']} files")
    
    if stats["prelib_remaining"] > 0:
        log(f"[VERIFY] WARNING: Files still in /pre-library - check if import worked correctly")
    
    return stats