# backend/services/discogs_refresh_scheduler.py
"""
Discogs Format Tag Scheduler for BeetsV7
Runs discogs_bulk_tag.py on a schedule to keep albumdisambig up-to-date.
Follows the same pattern as MetadataRefreshScheduler.
"""

import subprocess
import threading
import time
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class DiscogsRefreshScheduler:
    """
    Automated scheduler for Discogs format tag refresh.

    Supports two modes:
    1. Daily refresh at a specific time (e.g., 4 AM)
    2. Weekly refresh on a specific day (e.g., Sunday)

    Calls discogs_bulk_tag.py --move to update albumdisambig
    and rename folders for any newly tagged albums.
    """

    def __init__(
        self,
        mode: str = "weekly",
        refresh_time: str = "04:00",
        refresh_day: int = 6,  # 0=Monday, 6=Sunday
    ):
        """
        Initialize the Discogs refresh scheduler.

        Args:
            mode: "daily" or "weekly"
            refresh_time: Time to run (HH:MM, 24-hour)
            refresh_day: Day of week for weekly mode (0=Mon, 6=Sun)
        """
        self.mode = mode
        self.refresh_time = refresh_time
        self.refresh_day = refresh_day
        self.running = False
        self.thread = None
        self.last_run = None
        self.last_result = None
        self.script_path = Path("/app/scripts/discogs_bulk_tag.py")

    def _run_refresh(self, force: bool = False):
        """Execute the discogs bulk tag script."""
        try:
            cmd = ["python3", str(self.script_path), "--move"]
            if force:
                cmd.append("--force")

            logger.info("[DISCOGS REFRESH] Starting bulk tag refresh (force={})...".format(force))
            self.last_run = datetime.now().isoformat()

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False
            )

            if result.returncode == 0:
                logger.info("[DISCOGS REFRESH] Completed successfully")
                self.last_result = "success"
            else:
                logger.warning("[DISCOGS REFRESH] Exited with code {}".format(result.returncode))
                if result.stderr:
                    logger.error("[DISCOGS REFRESH] Error: {}".format(result.stderr[:500]))
                self.last_result = "error"

        except Exception as e:
            logger.error("[DISCOGS REFRESH] Error running refresh: {}".format(e))
            self.last_result = "error"

    def _seconds_until_next_run(self) -> int:
        """Calculate seconds until next scheduled run."""
        now = datetime.now()
        hour, minute = map(int, self.refresh_time.split(":"))

        if self.mode == "daily":
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                # Schedule for tomorrow
                from datetime import timedelta
                target = target + timedelta(days=1)

        else:  # weekly
            from datetime import timedelta
            days_ahead = self.refresh_day - now.weekday()
            if days_ahead < 0:
                days_ahead += 7
            elif days_ahead == 0 and now.hour >= hour and now.minute >= minute:
                days_ahead = 7
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            target = target + timedelta(days=days_ahead)

        delta = target - now
        return int(delta.total_seconds())

    def _scheduler_loop(self):
        """Main scheduler loop."""
        mode_desc = "daily at {}".format(self.refresh_time) if self.mode == "daily" \
            else "weekly on day {} at {}".format(self.refresh_day, self.refresh_time)
        logger.info("[DISCOGS REFRESH] Scheduler running - {}".format(mode_desc))

        while self.running:
            sleep_seconds = self._seconds_until_next_run()
            logger.info("[DISCOGS REFRESH] Next run in {:.1f} hours".format(
                sleep_seconds / 3600))

            # Sleep in 60-second chunks to allow clean shutdown
            for _ in range(sleep_seconds // 60):
                if not self.running:
                    return
                time.sleep(60)

            if self.running:
                time.sleep(sleep_seconds % 60)

            if self.running:
                self._run_refresh(force=False)

    def start(self):
        """Start the scheduler in a background thread."""
        if self.running:
            logger.warning("[DISCOGS REFRESH] Already running")
            return

        self.running = True
        self.thread = threading.Thread(
            target=self._scheduler_loop,
            daemon=True,
            name="DiscogsRefreshScheduler"
        )
        self.thread.start()
        logger.info("[DISCOGS REFRESH] Started in {} mode".format(self.mode.upper()))

    def stop(self):
        """Stop the scheduler."""
        if not self.running:
            return

        logger.info("[DISCOGS REFRESH] Stopping...")
        self.running = False

        if self.thread:
            self.thread.join(timeout=5)

        logger.info("[DISCOGS REFRESH] Stopped")

    def run_now(self, force: bool = False):
        """Manually trigger a refresh immediately (non-blocking)."""
        logger.info("[DISCOGS REFRESH] Manual trigger requested (force={})".format(force))
        t = threading.Thread(
            target=lambda: self._run_refresh(force),
            daemon=True
        )
        t.start()

    def get_status(self) -> dict:
        """Get current scheduler status."""
        status = {
            "running": self.running,
            "mode": self.mode,
            "refresh_time": self.refresh_time,
            "thread_alive": self.thread.is_alive() if self.thread else False,
            "last_run": self.last_run,
            "last_result": self.last_result,
        }

        if self.mode == "weekly":
            status["refresh_day"] = self.refresh_day

        if self.running:
            status["next_run_in_hours"] = round(
                self._seconds_until_next_run() / 3600, 1)

        return status


# Singleton instance
_discogs_scheduler = None


def get_discogs_scheduler(
    mode: str = "weekly",
    refresh_time: str = "04:00",
    refresh_day: int = 6,
) -> DiscogsRefreshScheduler:
    """
    Get or create the global Discogs refresh scheduler instance.

    Args:
        mode: "daily" or "weekly"
        refresh_time: Time for refresh (HH:MM, 24-hour)
        refresh_day: Day of week for weekly mode (0=Mon, 6=Sun)
    """
    global _discogs_scheduler
    if _discogs_scheduler is None:
        _discogs_scheduler = DiscogsRefreshScheduler(
            mode=mode,
            refresh_time=refresh_time,
            refresh_day=refresh_day,
        )
    return _discogs_scheduler