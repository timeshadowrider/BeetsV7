# backend/services/pipeline_scheduler.py
"""
Continuous Pipeline Scheduler for BeetsV7
Runs the pipeline in a continuous loop - starts again immediately after completion.
Also supports interval-based scheduling.

Changes:
- _is_pipeline_running() now checks for a live process before trusting the lock file.
  Previously a stale lock file (left by a crash or container restart) would block the
  scheduler forever -- it would see the lock, wait 30 seconds, see it again, wait again,
  indefinitely. Now if the lock exists but no pipeline_controller_v7.py process is
  running, the lock is cleared automatically and the pipeline starts fresh.
- _run_pipeline() no longer uses capture_output=True -- output now flows through to
  docker logs so pipeline errors are visible instead of disappearing silently.
"""

import subprocess
import threading
import time
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class PipelineScheduler:
    """
    Automated scheduler for running the pipeline.
    Supports two modes:
    1. Continuous loop - runs again immediately after completion
    2. Interval-based - waits X minutes between runs
    """

    def __init__(self, mode: str = "continuous", interval_minutes: int = 10):
        """
        Initialize the pipeline scheduler.

        Args:
            mode: "continuous" or "interval"
                - continuous: Runs again immediately after completion
                - interval: Waits interval_minutes between runs
            interval_minutes: How long to wait between runs (only for interval mode)
        """
        self.mode = mode
        self.interval_minutes = interval_minutes
        self.running = False
        self.thread = None
        self.lock_file = Path("/data/pipeline.lock")

    def _is_pipeline_running(self) -> bool:
        """
        Check if the pipeline is currently running via lock file.

        FIX: Previously just checked lock file existence. A stale lock left by a
        crash or container restart would block the scheduler forever. Now we verify
        a live pipeline_controller_v7.py process actually exists. If the lock is
        present but no process is found, the lock is stale and gets cleared.
        """
        if not self.lock_file.exists():
            return False

        # Lock exists -- check if a live process owns it
        result = subprocess.run(
            ["pgrep", "-f", "pipeline_controller_v7.py"],
            capture_output=True
        )

        if result.returncode != 0:
            # No live process found -- stale lock
            logger.warning("[SCHEDULER] Stale lock file detected (no live pipeline process), clearing...")
            try:
                self.lock_file.unlink(missing_ok=True)
            except Exception as e:
                logger.error(f"[SCHEDULER] Could not remove stale lock: {e}")
            return False

        return True

    def _run_pipeline(self):
        """
        Execute the pipeline controller script.

        FIX: Removed capture_output=True so pipeline stdout/stderr flows through
        to docker logs. Previously errors were swallowed silently -- the scheduler
        would log 'Pipeline exited with code 1' but the actual traceback was lost.
        """
        try:
            logger.info(f"[SCHEDULER] Starting pipeline run at {datetime.now()}")

            result = subprocess.run(
                ["python3", "/app/scripts/pipeline_controller_v7.py"],
                check=False
            )

            if result.returncode == 0:
                logger.info("[SCHEDULER] Pipeline completed successfully")
            else:
                logger.warning(f"[SCHEDULER] Pipeline exited with code {result.returncode}")

        except Exception as e:
            logger.error(f"[SCHEDULER] Error running pipeline: {e}")

    def _continuous_loop(self):
        """
        Continuous loop mode - runs pipeline again immediately after completion.
        Includes a small delay to prevent CPU spinning.
        """
        logger.info("[SCHEDULER] Starting CONTINUOUS loop mode")

        while self.running:
            # Check for stale lock before waiting
            if self._is_pipeline_running():
                logger.debug("[SCHEDULER] Pipeline already running, waiting...")
                time.sleep(30)
                continue

            # Run the pipeline
            self._run_pipeline()

            # Small cooldown before next run
            if self.running:
                time.sleep(10)

    def _interval_loop(self):
        """
        Interval-based mode - waits X minutes between runs.
        """
        logger.info(f"[SCHEDULER] Starting INTERVAL mode (every {self.interval_minutes} minutes)")

        while self.running:
            self._run_pipeline()

            if self.running:
                logger.info(f"[SCHEDULER] Waiting {self.interval_minutes} minutes until next run...")
                time.sleep(self.interval_minutes * 60)

    def start(self):
        """Start the scheduler in a background thread."""
        if self.running:
            logger.warning("[SCHEDULER] Already running")
            return

        # Clear any stale lock at startup before the loop begins
        if self.lock_file.exists():
            result = subprocess.run(
                ["pgrep", "-f", "pipeline_controller_v7.py"],
                capture_output=True
            )
            if result.returncode != 0:
                logger.warning("[SCHEDULER] Clearing stale lock file at startup...")
                self.lock_file.unlink(missing_ok=True)

        self.running = True

        if self.mode == "continuous":
            target = self._continuous_loop
        else:
            target = self._interval_loop

        self.thread = threading.Thread(target=target, daemon=True, name="PipelineScheduler")
        self.thread.start()

        logger.info(f"[SCHEDULER] Started in {self.mode.upper()} mode")

    def stop(self):
        """Stop the scheduler."""
        if not self.running:
            return

        logger.info("[SCHEDULER] Stopping...")
        self.running = False

        if self.thread:
            self.thread.join(timeout=5)

        logger.info("[SCHEDULER] Stopped")

    def run_now(self):
        """Manually trigger a pipeline run immediately (non-blocking)."""
        logger.info("[SCHEDULER] Manual trigger requested")
        t = threading.Thread(target=self._run_pipeline, daemon=True)
        t.start()

    def get_status(self) -> dict:
        """Get current scheduler status."""
        return {
            "running": self.running,
            "mode": self.mode,
            "interval_minutes": self.interval_minutes if self.mode == "interval" else None,
            "pipeline_active": self._is_pipeline_running(),
            "thread_alive": self.thread.is_alive() if self.thread else False
        }


# Singleton instance
_scheduler = None


def get_scheduler(mode: str = "continuous", interval_minutes: int = 10) -> PipelineScheduler:
    """
    Get or create the global scheduler instance.

    Args:
        mode: "continuous" (runs immediately after completion) or "interval" (waits between runs)
        interval_minutes: Only used in interval mode
    """
    global _scheduler
    if _scheduler is None:
        _scheduler = PipelineScheduler(mode=mode, interval_minutes=interval_minutes)
    return _scheduler