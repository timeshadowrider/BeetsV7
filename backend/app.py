# ---------------------------------------------------------
# Beets Replacement API (v7)
# ---------------------------------------------------------

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.routes import pipeline_v7, ui
from backend.services.watcher_service import start_inbox_settle_watcher

import os
import subprocess
import threading
from pathlib import Path

# ---------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------
app = FastAPI(title="Beets Replacement API (v7)")

# ---------------------------------------------------------
# CORS
# ---------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# Ensure static + public directories exist
# ---------------------------------------------------------
os.makedirs("/app/static", exist_ok=True)
os.makedirs("/app/public", exist_ok=True)

# ---------------------------------------------------------
# Register API routers
# ---------------------------------------------------------
app.include_router(pipeline_v7.router, prefix="/api")
app.include_router(ui.router, prefix="/api/ui")

# ---------------------------------------------------------
# Serve static assets
# ---------------------------------------------------------
app.mount("/static", StaticFiles(directory="/app/static"), name="static")

# ---------------------------------------------------------
# Serve the music library (covers, audio files)
# ---------------------------------------------------------
app.mount(
    "/music/library",
    StaticFiles(directory="/music/library"),
    name="library"
)


# ---------------------------------------------------------
# Serve the frontend (index.html)
# ---------------------------------------------------------
app.mount("/", StaticFiles(directory="/app/public", html=True), name="public")


# ---------------------------------------------------------
# NEW: Metadata Watcher
# ---------------------------------------------------------

METADATA_WATCHER_LOG = Path("/data/metadata_watcher.log")

def start_metadata_watcher():
    """
    Launch the metadata watcher script in the background.
    Logs are written to /data/metadata_watcher.log
    """
    METADATA_WATCHER_LOG.parent.mkdir(parents=True, exist_ok=True)

    with open(METADATA_WATCHER_LOG, "a", encoding="utf-8") as logf:
        subprocess.Popen(
            ["python3", "/app/scripts/watch_metadata.py"],
            stdout=logf,
            stderr=logf,
            bufsize=1,
            universal_newlines=True,
        )


# ---------------------------------------------------------
# Startup: watchers
# ---------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    print("[STARTUP] v7 backend starting watchers...")

    # Start inbox settle watcher
    start_inbox_settle_watcher()

    # Start metadata watcher
    threading.Thread(target=start_metadata_watcher, daemon=True).start()

    print("[STARTUP] Watchers started.")
