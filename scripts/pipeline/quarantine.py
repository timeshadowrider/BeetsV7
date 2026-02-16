#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import shutil
from pathlib import Path
import time

FAILED_IMPORTS_NAME = "failed_imports"
QUARANTINE_ROOT = Path("/music/quarantine/failed_imports")


def _ts():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def qlog(msg: str):
    line = f"[{_ts()}] [quarantine] {msg}"
    print(line)


def sanitize_for_filename(text: str) -> str:
    illegal = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    for ch in illegal:
        text = text.replace(ch, '-')
    return text


def flatten_quarantine_filename(original_path: Path) -> str:
    parts = [p for p in original_path.parts if p not in ("", "/", FAILED_IMPORTS_NAME)]
    filename = " - ".join(parts)
    return sanitize_for_filename(filename)


def is_failed_imports_folder(path: Path) -> bool:
    return path.name == FAILED_IMPORTS_NAME


def _safe_delete(src: Path):
    try:
        os.remove(src)
        return
    except PermissionError:
        try:
            os.chmod(src, 0o666)
            os.remove(src)
            return
        except Exception as e:
            qlog(f"WARNING: could not delete {src}: {e}")
    except Exception as e:
        qlog(f"WARNING: could not delete {src}: {e}")

    # Last resort: mark as stuck
    try:
        stuck = src.with_suffix(src.suffix + ".stuck")
        src.rename(stuck)
        qlog(f"Marked as stuck: {stuck}")
    except Exception as e:
        qlog(f"WARNING: could not mark {src} as stuck: {e}")


def quarantine_folder(path: Path):
    """
    Move all files from a failed_imports folder into the global quarantine root.
    Skip if the folder *is* the quarantine root.
    """
    if not path.exists():
        return

    # NEW: Do not quarantine the quarantine root itself
    if path.resolve() == QUARANTINE_ROOT.resolve():
        qlog(f"SKIP: refusing to quarantine the quarantine root {path}")
        return

    QUARANTINE_ROOT.mkdir(parents=True, exist_ok=True)

    for root, dirs, files in os.walk(path):
        for f in files:
            src = Path(root) / f

            # Compute flattened filename
            rel = src.relative_to(path.parent)
            flat_name = flatten_quarantine_filename(rel)
            dst = QUARANTINE_ROOT / flat_name

            # NEW: Skip if src == dst (prevents SameFileError)
            if src.resolve() == dst.resolve():
                qlog(f"SKIP: src and dst are same file, skipping {src}")
                continue

            dst.parent.mkdir(parents=True, exist_ok=True)
            qlog(f"QUARANTINE: {src} -> {dst}")

            try:
                shutil.copy2(src, dst)
            except shutil.SameFileError:
                qlog(f"SKIP: SameFileError for {src}, already quarantined")
                continue

            _safe_delete(src)

    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception as e:
        qlog(f"WARNING: could not remove folder {path}: {e}")


def quarantine_failed_imports_global(root_path: Path):
    """
    Walk a directory tree and quarantine any folder named failed_imports,
    EXCEPT the real quarantine root.
    """
    if not root_path.exists():
        return

    for current_root, dirs, files in os.walk(root_path):
        for d in list(dirs):
            if d == FAILED_IMPORTS_NAME:
                folder = Path(current_root) / d

                # NEW: Skip the real quarantine root
                if folder.resolve() == QUARANTINE_ROOT.resolve():
                    qlog(f"SKIP: ignoring quarantine root {folder}")
                    dirs.remove(d)
                    continue

                qlog(f"FOUND failed_imports folder: {folder}")
                quarantine_folder(folder)

                # Prevent descending into it again
                dirs.remove(d)
