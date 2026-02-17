# backend/app.py
"""
BeetsV7 FastAPI Backend - Complete Version
Includes:
- Continuous pipeline scheduler
- Inbox settle watcher
- Metadata watcher
- Metadata refresh scheduler
- Discogs format tag refresh scheduler
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import logging
import os
import subprocess
import threading
from pathlib import Path

# Import routers
from backend.routes import pipeline_v7, ui
from backend.services.watcher_service import start_inbox_settle_watcher
from backend.services.pipeline_scheduler import get_scheduler
from backend.services.metadata_refresh_scheduler import get_metadata_scheduler
from backend.services.discogs_refresh_scheduler import get_discogs_scheduler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# Metadata Watcher
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
# Lifespan context manager - handles startup/shutdown
# ---------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifespan events.
    Starts all watchers and schedulers on startup, stops them on shutdown.
    """
    # STARTUP
    logger.info("?? Starting BeetsV7 Backend v7.4...")

    # 1. Start inbox settle watcher
    logger.info("[STARTUP] Starting inbox settle watcher...")
    start_inbox_settle_watcher()

    # 2. Start metadata watcher
    logger.info("[STARTUP] Starting metadata watcher...")
    threading.Thread(target=start_metadata_watcher, daemon=True).start()

    # 3. Start the pipeline scheduler
    mode = os.getenv("PIPELINE_MODE", "continuous")
    interval_minutes = int(os.getenv("PIPELINE_INTERVAL_MINUTES", "10"))

    pipeline_scheduler = get_scheduler(mode=mode, interval_minutes=interval_minutes)
    pipeline_scheduler.start()

    if mode == "continuous":
        logger.info("?? Pipeline in CONTINUOUS mode - runs immediately after completion")
    else:
        logger.info(f"??  Pipeline in INTERVAL mode - runs every {interval_minutes} minutes")

    # 4. Start metadata refresh scheduler
    metadata_mode = os.getenv("METADATA_REFRESH_MODE", "daily")
    metadata_time = os.getenv("METADATA_REFRESH_TIME", "03:00")
    metadata_interval = int(os.getenv("METADATA_REFRESH_INTERVAL_HOURS", "6"))

    metadata_scheduler = get_metadata_scheduler(
        mode=metadata_mode,
        refresh_time=metadata_time,
        interval_hours=metadata_interval
    )
    metadata_scheduler.start()

    # 5. Start Discogs format tag refresh scheduler
    discogs_mode = os.getenv("DISCOGS_REFRESH_MODE", "weekly")
    discogs_time = os.getenv("DISCOGS_REFRESH_TIME", "04:00")
    discogs_day = int(os.getenv("DISCOGS_REFRESH_DAY", "6"))  # 6 = Sunday

    discogs_scheduler = get_discogs_scheduler(
        mode=discogs_mode,
        refresh_time=discogs_time,
        refresh_day=discogs_day,
    )
    discogs_scheduler.start()

    logger.info("? All watchers and schedulers started successfully")

    yield  # Application is now running

    # SHUTDOWN
    logger.info("?? Shutting down BeetsV7 Backend...")
    pipeline_scheduler.stop()
    metadata_scheduler.stop()
    discogs_scheduler.stop()
    logger.info("? Shutdown complete")

# ---------------------------------------------------------
# Create FastAPI app with lifespan
# ---------------------------------------------------------
app = FastAPI(
    title="BeetsV7 Music Pipeline API",
    description="Event-driven music ingestion pipeline with continuous processing",
    version="7.4",
    lifespan=lifespan
)

# ---------------------------------------------------------
# CORS Middleware
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
# Health check endpoints
# ---------------------------------------------------------
@app.get("/api/health")
def health_check():
    """Detailed health check including all scheduler status."""
    pipeline_scheduler = get_scheduler()
    pipeline_status = pipeline_scheduler.get_status()

    metadata_scheduler = get_metadata_scheduler()
    metadata_status = metadata_scheduler.get_status()

    discogs_scheduler = get_discogs_scheduler()
    discogs_status = discogs_scheduler.get_status()

    return {
        "status": "healthy",
        "version": "7.4",
        "service": "BeetsV7 Music Pipeline API",
        "pipeline_scheduler": pipeline_status,
        "metadata_scheduler": metadata_status,
        "discogs_scheduler": discogs_status,
        "watchers": {
            "inbox_settle": "running",
            "metadata": "running",
            "pipeline_scheduler": pipeline_status["running"],
            "metadata_refresh": metadata_status["running"],
            "discogs_refresh": discogs_status["running"],
        }
    }

@app.get("/api/scheduler/pipeline")
def pipeline_scheduler_status():
    """Get pipeline scheduler status."""
    scheduler = get_scheduler()
    return scheduler.get_status()

@app.get("/api/scheduler/metadata")
def metadata_scheduler_status():
    """Get metadata refresh scheduler status."""
    scheduler = get_metadata_scheduler()
    return scheduler.get_status()

@app.post("/api/scheduler/metadata/run")
def trigger_metadata_refresh(quick: bool = False):
    """Manually trigger metadata refresh."""
    scheduler = get_metadata_scheduler()
    scheduler.run_now(quick=quick)
    return {
        "status": "started",
        "type": "quick" if quick else "full",
        "message": f"Metadata refresh {'(quick)' if quick else '(full)'} started in background"
    }

@app.get("/api/scheduler/discogs")
def discogs_scheduler_status():
    """Get Discogs format tag refresh scheduler status."""
    scheduler = get_discogs_scheduler()
    return scheduler.get_status()

@app.post("/api/scheduler/discogs/run")
def trigger_discogs_refresh(force: bool = False):
    """Manually trigger Discogs format tag refresh."""
    scheduler = get_discogs_scheduler()
    scheduler.run_now(force=force)
    return {
        "status": "started",
        "force": force,
        "message": "Discogs refresh {}started in background".format(
            "(force re-tag all) " if force else ""
        )
    }

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
# Serve the frontend (index.html) - MUST BE LAST
# ---------------------------------------------------------
app.mount("/", StaticFiles(directory="/app/public", html=True), name="public")