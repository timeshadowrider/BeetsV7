"""
backend/services/regenerate_scheduler.py

Runs generate_ui_json() on a background thread every N minutes.
Optionally runs beets_metadata_refresh.py after each regeneration cycle.

Completely independent of the pipeline — the frontend will never
show stale stats even if the pipeline gets stuck or takes a long time.

Environment variables:
    REGEN_INTERVAL_MINUTES      How often to regenerate UI JSON (default: 15)
    REGEN_WITH_METADATA         Run metadata refresh after each regen (default: false)
    METADATA_REFRESH_QUICK      Use --quick mode for metadata refresh (default: true)
"""

import threading
import time
import logging
import subprocess
import sys
import os

logger = logging.getLogger(__name__)

_scheduler_instance = None


class RegenerateScheduler:
    def __init__(self, interval_minutes: int = 15):
        self.interval_seconds = interval_minutes * 60
        self._stop_event = threading.Event()
        self._thread = None
        self._running = False
        self._last_run = None
        self._last_status = "never run"
        self._last_metadata_status = "never run"

        # Read env vars at init time (can be overridden before start())
        self.with_metadata = os.getenv("REGEN_WITH_METADATA", "false").lower() == "true"
        self.metadata_quick = os.getenv("METADATA_REFRESH_QUICK", "true").lower() == "true"

    def _run_regenerate(self):
        """Run incremental UI JSON regeneration."""
        try:
            sys.path.insert(0, "/app")
            from scripts.pipeline.regenerate import generate_ui_json
            logger.info("[regen_scheduler] Starting incremental UI JSON regeneration...")
            generate_ui_json()
            self._last_status = "ok"
            logger.info("[regen_scheduler] UI JSON regeneration complete.")
            return True
        except Exception as e:
            self._last_status = "error: %s" % e
            logger.error("[regen_scheduler] Regeneration failed: %s" % e)
            return False

    def _run_metadata_refresh(self):
        """Run beets metadata refresh script."""
        mode = "--quick" if self.metadata_quick else ""
        cmd = ["python3", "/app/scripts/beets_metadata_refresh.py"]
        if mode:
            cmd.append(mode)

        logger.info("[regen_scheduler] Starting metadata refresh (%s)..." %
                    ("quick" if self.metadata_quick else "full"))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=7200  # 2 hour max
            )
            if result.returncode == 0:
                self._last_metadata_status = "ok"
                logger.info("[regen_scheduler] Metadata refresh complete.")
            else:
                self._last_metadata_status = "exit code %d" % result.returncode
                logger.warning("[regen_scheduler] Metadata refresh exited %d: %s" %
                               (result.returncode, result.stderr[:300]))
        except subprocess.TimeoutExpired:
            self._last_metadata_status = "timeout"
            logger.error("[regen_scheduler] Metadata refresh timed out after 2 hours.")
        except Exception as e:
            self._last_metadata_status = "error: %s" % e
            logger.error("[regen_scheduler] Metadata refresh failed: %s" % e)

    def _run_once(self):
        """Run one full cycle: regenerate JSON, then optionally metadata refresh."""
        regen_ok = self._run_regenerate()

        if regen_ok and self.with_metadata:
            self._run_metadata_refresh()
        elif not self.with_metadata:
            self._last_metadata_status = "disabled"

        self._last_run = time.time()

    def _loop(self):
        logger.info("[regen_scheduler] Starting — interval: %ds, metadata_refresh: %s (%s)" % (
            self.interval_seconds,
            "enabled" if self.with_metadata else "disabled",
            "quick" if self.metadata_quick else "full"
        ))

        # Run immediately on startup so stats are fresh after every container restart
        self._run_once()

        while not self._stop_event.is_set():
            # Sleep in 1s increments so stop() is responsive
            for _ in range(self.interval_seconds):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

            if not self._stop_event.is_set():
                self._run_once()

        logger.info("[regen_scheduler] Stopped.")

    def start(self):
        if self._running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="regen-scheduler")
        self._thread.start()
        self._running = True
        logger.info("[regen_scheduler] Started (interval: %d min)" % (self.interval_seconds // 60))

    def stop(self):
        self._stop_event.set()
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)

    def run_now(self, with_metadata: bool = None):
        """
        Trigger an immediate out-of-schedule cycle (non-blocking).
        Pass with_metadata=True/False to override the default for this run.
        """
        def _job():
            if with_metadata is not None:
                orig = self.with_metadata
                self.with_metadata = with_metadata
                self._run_once()
                self.with_metadata = orig
            else:
                self._run_once()

        t = threading.Thread(target=_job, daemon=True, name="regen-on-demand")
        t.start()

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "interval_minutes": self.interval_seconds // 60,
            "last_run": self._last_run,
            "last_status": self._last_status,
            "last_metadata_status": self._last_metadata_status,
            "metadata_refresh_enabled": self.with_metadata,
            "metadata_refresh_mode": "quick" if self.metadata_quick else "full",
        }


def get_regenerate_scheduler(interval_minutes: int = 15) -> RegenerateScheduler:
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = RegenerateScheduler(interval_minutes=interval_minutes)
    return _scheduler_instance