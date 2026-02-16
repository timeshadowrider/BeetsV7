?? Beets v7 — Event-Driven Music Ingestion Pipeline
Automated, fault-tolerant, metadata-aware music processing for SABnzbd + SLSKD + Beets + Navidrome + Volumio
Beets v7 is a fully automated, event-driven music ingestion pipeline designed for home-lab environments. It coordinates multiple services — SABnzbd, SLSKD, Beets, fingerprinting, Navidrome, and Volumio — to reliably ingest, normalize, fingerprint, tag, and organize music files with zero manual intervention.

This version includes a complete rewrite of the pipeline controller, improved stability, SLSKD API integration, album-aware processing, and a deterministic pre-library staging system.

?? Features
Event-Driven Ingestion
The pipeline automatically processes new music only when:

SABnzbd has finished the job

SLSKD has finished downloading all files for that artist

The folder has “settled” (no writes for a configurable time window)

This prevents partial imports, corrupted metadata, and race conditions.

Pre-Library Staging (/pre-library)
All incoming music is normalized and validated in a staging area before entering the canonical library:

Album folders are created deterministically

Loose tracks are grouped by albumartist/album tags

Large groups are chunked into batches

Fingerprinting is applied before import

Beets imports only clean, validated files

Beets Integration
Beets handles:

Metadata enrichment

Tag normalization

Moving files into /music/library

Updating existing library entries

The pipeline runs:

Code
beet import
beet update
beet move
in the correct order for deterministic results.

SLSKD Integration
The pipeline uses the SLSKD API to detect active Soulseek transfers:

Code
GET /api/v0/transfers
Authentication is done via:

Code
X-API-Key: <your-api-key>
This prevents the pipeline from processing incomplete Soulseek downloads.

SABnzbd Integration
The pipeline queries SABnzbd’s queue API to detect active jobs and match them to artist folders.

Automatic Metadata Fingerprinting
Every batch of files is fingerprinted using:

Code
python3 /app/scripts/fingerprint_all.py
This ensures accurate MusicBrainz matching during Beets import.

Automatic Library Refresh
After each pipeline run:

Navidrome scan is triggered

Volumio rescan is triggered

Library permissions are corrected

UI JSON is regenerated for the frontend

Quarantine System
Any failed imports in /pre-library are automatically moved to:

Code
/pre-library/failed_imports
This prevents bad files from polluting the main library.

Verbose Logging + Status JSON
The pipeline writes:

pipeline.log — high-level events

pipeline_verbose.log — detailed debugging

pipeline_status.json — current state for the frontend

?? Directory Structure
Code
Beets-v7/
+-- scripts/
¦   +-- pipeline_controller_v7.py
¦   +-- fingerprint_all.py
¦   +-- regenerate_albums_v7.py
¦   +-- cleanup_non_audio_files_v7.py
+-- pipeline/
¦   +-- quarantine.py
¦   +-- regenerate.py
+-- docker/
¦   +-- Dockerfile
¦   +-- compose.yaml
+-- volumes/
    +-- inbox/
    +-- pre-library/
    +-- music/library/
    +-- quarantine/
    +-- logs/
?? Configuration
Environment Variables (recommended)
Variable	Purpose
SLSKD_API_KEY	API key for SLSKD
SLSKD_HOST	Base URL for SLSKD (e.g., http://slskd:5030)
SABNZBD_API_KEY	SABnzbd API key
SABNZBD_HOST	SABnzbd base URL
NAVIDROME_HOST	Navidrome base URL
NAVIDROME_USER	Navidrome username
NAVIDROME_PASSWORD	Navidrome password
VOLUMIO_HOST	Volumio host/IP
Your pipeline controller supports hard-coded values, but environment variables are strongly recommended for public deployments.

?? How the Pipeline Works
1. Detect artist folders in /inbox
Skips:

_UNPACK_ folders

failed_imports

Empty folders

2. Check SABnzbd + SLSKD
If either is still processing ? skip.

3. Grace period
Folder must be idle for a configurable number of seconds.

4. Cleanup
Removes junk files and empty directories.

5. Album folder handling
Moves album subfolders into /pre-library.

6. Loose file grouping
Groups by:

albumartist

album

7. Chunking
Large groups are processed in batches.

8. Fingerprinting
Ensures accurate metadata matching.

9. Beets import
Imports into /music/library.

10. Post-processing
Updates metadata, moves files, refreshes library.

?? Running the Pipeline
Inside the container:

bash
docker exec -it beetsV7 python3 /app/scripts/pipeline_controller_v7.py
?? SLSKD API Example
Test endpoint:

bash
curl -H "X-API-Key: <your-api-key>" \
     http://<slskd-host>:5030/api/v0/application
?? Testing the Pipeline
Drop a folder into:

Code
volumes/inbox/Artist Name/
Watch logs:

bash
docker logs -f beetsV7
Or check:

Code
/data/pipeline.log
/data/pipeline_verbose.log
/data/pipeline_status.json
?? Development Notes
The pipeline is idempotent

All destructive operations are safe

Every step logs to both stdout and file

The system is designed to survive container restarts

All paths are absolute and volume-mounted

?? Roadmap
Global settle logic

Async parallel ingestion

REST API for pipeline control

Web UI for pipeline status

?? Credits
Built for home-lab automation and deterministic media management.
Designed for reproducibility, transparency, and maintainability.