# BeetsV7

A self-hosted music library automation system built on [beets](https://beets.io/), running in Docker on OpenMediaVault. Manages a FLAC/MP3 library of 8,000+ tracks with automated ingestion, metadata enrichment, deduplication, and multi-player synchronization.

---

## Overview

BeetsV7 is a hybrid pipeline that continuously watches an inbox folder, processes new music through a series of quality and safety checks, imports it into a organized library via beets, and notifies downstream media players. It integrates with SLSKD for automated downloads from Soulseek, Lidarr for library gap detection, and supports Plex, Navidrome, and Volumio as playback targets.

---

## Architecture

```
Soulseek (SLSKD) 
SABnzbd 
Manual drops  /inbox  /pre-library (tmpfs)  /music/library
                                         
                                    beets import
                                    fingerprint
                                    dedup
                                         
                              Plex / Navidrome / Volumio
```

### Key Components

| Component | Description |
|-----------|-------------|
| `pipeline_controller_v7.py` | Main orchestrator — watches inbox, chunks albums into batches, drives the full import cycle |
| `scripts/pipeline/` | Modular pipeline subsystems (moves, beets, metadata, cleanup, quarantine, etc.) |
| `scripts/fingerprint_all.py` | AcoustID fingerprinting with mtime-based incremental scanning |
| `scripts/beets_metadata_refresh.py` | Scheduled full metadata refresh (MusicBrainz, artwork, lyrics, genres) |
| `scripts/discogs_bulk_tag.py` | Bulk Discogs tagger for format descriptions and primary artist consolidation |
| `backend/` | FastAPI backend serving the web UI |
| `public/` / `static/` | Web dashboard frontend |

---

## Pipeline Flow

Each pipeline run follows this sequence:

1. **Lock** — file-based lock prevents concurrent runs; auto-clears stale locks from container restarts
2. **Quarantine** — moves any `failed_imports` folders out of pre-library to `/music/quarantine`
3. **Clear pre-library** — wipes the tmpfs pre-library so leftover files from previous runs don't accumulate
4. **SLSKD check** — fetches active transfer list; artists with active downloads are skipped (re-checked per-artist)
5. **Per-artist processing:**
   - SABnzbd active job check
   - Settle timer (5 minute grace period for new downloads)
   - Junk file cleanup (NFO, CUE, logs, etc.)
   - Corruption check on all audio files
   - Move album folders  pre-library (tmpfs RAM disk)
   - AcoustID fingerprinting
   - beets import
   - Post-import move/update scoped to last 24h
6. **Permissions fix**, UI JSON regeneration, Navidrome scan trigger, Volumio rescan

### Chunking

Albums are processed in configurable chunks (`CHUNK_SIZE = 500`) with a fingerprint  import  post-process cycle per chunk. This keeps pre-library memory usage bounded on large artist backlogs.

---

## Pre-library (tmpfs)

`/pre-library` is a tmpfs RAM disk used as a staging area between inbox and library. Files are moved here before beets processes them, giving fast I/O during import.

**Important:** Pre-library is wiped at the start of every pipeline run. Files that beets rejects (duplicates, unmatched) are not preserved — Lidarr acts as the source of truth for missing albums and will re-queue anything that doesn't make it through.

Configure size in `docker-compose.yml`:
```yaml
tmpfs:
  - /pre-library:size=8g
```

Increase if you see `[Errno 28] No space left on device` errors during large batch imports.

---

## Metadata Enrichment

### On Import
- AcoustID fingerprinting before beets import
- MusicBrainz matching (auto + as-is fallback)
- Artwork fetching and embedding

### Nightly (3 AM)
`beets_metadata_refresh.py` runs a full refresh cycle:
1. Orphaned duplicate record cleanup (`.1.flac`, `.1.mp3` stale DB entries)
2. Fingerprint unmatched tracks  MusicBrainz sync
3. Move files to correct paths (post-mbsync renames)
4. Fetch missing artwork  embed
5. Fetch lyrics, update genres (Last.fm)
6. Scrub/normalize metadata
7. Smart playlist generation
8. Notify Plex, Navidrome, MPD

### Weekly (Sunday 4 AM)
`discogs_bulk_tag.py` queries Discogs for each album and applies:
- `albumdisambig` — meaningful format tags (Remastered, Deluxe Edition, etc.)
- `albumartist_primary` — primary artist for path template consolidation

This ensures collaborative releases like `Gabry Ponte & Datura` are filed under `Gabry Ponte/` in the library while preserving the original credit in metadata.

---

## Safety Systems

### SLSKD Integration
- Active transfers are checked before processing each artist folder
- Fuzzy token matching prevents processing partially-downloaded folders
- Transfer list is refreshed per-artist (not a stale startup snapshot)
- 10-minute timeout prevents infinite blocking on stuck queues

### SABnzbd Integration
- Only blocks on genuinely active statuses (Downloading, Verifying, Extracting, etc.)
- Paused/Failed/Completed jobs do not block processing

### Settle Timer
- Artist folders must be idle for 5 minutes before processing
- Prevents importing mid-download files

### Corruption Check
- Every audio file is checked for readability and minimum size before import
- Corrupted files are moved to `/music/quarantine/failed_imports`

### Deduplication
- Pre-library is scanned for duplicate audio using AcoustID fingerprints before import
- Orphaned `.1.flac` / `.1.mp3` database records are cleaned up nightly

---

## Library Organization

```
/music/library/
  {albumartist_primary or albumartist}/
    ({year}) {album}/
      {track:02d} {title}.{ext}
```

Collaborative artists are grouped under the primary artist via the `albumartist_primary` custom beets field, populated by the Discogs tagger. The original `albumartist` credit is preserved in file metadata.

---

## Media Player Integration

| Player | Integration |
|--------|-------------|
| Plex | `beet plexupdate` after import and metadata refresh |
| Navidrome | REST API scan trigger (`/rest/startScan`) |
| Volumio | SSH `volumio rescan` command |
| MPD | `beet mpdupdate` |

---

## Web Dashboard

A FastAPI + React dashboard is served on port `7080` providing:
- Library stats (artists, albums, tracks, total duration)
- Recently added albums with cover art
- Pipeline status and current activity
- Inbox and pre-library file counts

UI JSON is regenerated incrementally every 15 minutes — only changed album folders are rescanned, making updates fast even on large libraries.

---

## Directory Structure

```
Beets-v7/
 docker/
    docker-compose.yml
 config/
    config.yaml          # beets configuration
 scripts/
    pipeline/            # pipeline subsystem modules
       beets.py
       cleanup.py
       fuzzy.py
       logging.py
       metadata.py
       moves.py
       quarantine.py
       regenerate.py
       sabnzbd.py
       settle.py
       slskd.py
       system_hooks.py
       util.py
    pipeline_controller_v7.py
    beets_metadata_refresh.py
    discogs_bulk_tag.py
    fingerprint_all.py
    cleanup_non_audio_files_v7.py
 backend/                 # FastAPI application
 public/                  # Web UI assets
 static/
 data/                    # Runtime data (gitignored)
    library.db           # beets database
    fingerprints.json    # AcoustID cache
    *.log
 entrypoint.sh
```

---

## Docker Volumes

| Container Path | Purpose |
|----------------|---------|
| `/inbox` | Incoming music from SLSKD/SABnzbd |
| `/pre-library` | tmpfs staging area (RAM disk) |
| `/music/library` | Final organized library |
| `/music/quarantine` | Failed imports and corrupted files |
| `/data` | beets DB, logs, pipeline state |
| `/config` | beets config.yaml |

---

## Configuration

Key settings in `docker-compose.yml`:

```yaml
environment:
  - BEETS_CONFIG=/config/config.yaml
  - LIBRARY_PATH=/music/library
  - INBOX_PATH=/inbox

tmpfs:
  - /pre-library:size=8g    # Increase if large batches fill this up
```

Key settings in `pipeline_controller_v7.py`:

```python
CHUNK_SIZE = 500            # Albums per import chunk
LOCK_FILE = "/data/pipeline.lock"
```

---

## Requirements

- Docker + Docker Compose
- OpenMediaVault (or any Linux host with sufficient RAM)
- 8GB+ RAM recommended for tmpfs pre-library
- Chromaprint (`fpcalc`) for AcoustID fingerprinting
- ffprobe for audio integrity checking

---

## Changelog

### v7.6
- Added `clear_prelibrary()` — wipes pre-library at start of each run to prevent tmpfs accumulation from rejected/skipped files

### v7.5
- Per-artist SLSKD transfer refresh (replaces stale startup snapshot)
- Removed `global_settle()` hard gate; pipeline now processes non-active artists immediately

### v7.4
- Fuzzy token matching for SLSKD active transfer detection
- Numeric token filtering prevents false positive folder matches
- SABnzbd integration limited to genuinely active statuses only
- Quarantine module uses `shutil.move` instead of copy+delete

### v7.3
- Incremental UI JSON regeneration (mtime-based cache, full rescan only on first run)
- Background scheduler for 15-minute UI refresh

### Earlier
- AcoustID fingerprint DB with mtime-based incremental scanning
- Orphaned duplicate record cleanup in nightly metadata refresh
- Discogs bulk tagger with primary artist consolidation
- `albumartist_primary` custom field for path template organization