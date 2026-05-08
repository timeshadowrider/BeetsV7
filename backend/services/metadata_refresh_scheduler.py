# backend/services/metadata_refresh_scheduler.py
"""
Metadata Refresh Scheduler for BeetsV7
Runs Beets plugins on a schedule to keep metadata up-to-date.
"""

import subprocess
import threading
import time
import logging
from datetime import datetime, time as datetime_time
from pathlib import Path

logger = logging.getLogger(__name__)


class MetadataRefreshScheduler:
    """
    Automated scheduler for Beets metadata refresh operations.
    
    Supports two modes:
    1. Daily refresh at a specific time (e.g., 3 AM)
    2. Interval-based refresh (e.g., every 6 hours)
    """
    
    def __init__(self, mode: str = "daily", refresh_time: str = "03:00", interval_hours: int = 6):
        """
        Initialize the metadata refresh scheduler.
        
        Args:
            mode: "daily" (run at specific time) or "interval" (run every X hours)
            refresh_time: Time to run daily refresh (HH:MM format, 24-hour)
            interval_hours: Hours between runs (for interval mode)
        """
        self.mode = mode
        self.refresh_time = refresh_time
        self.interval_hours = interval_hours
        self.running = False
        self.thread = None
        self.script_path = Path("/app/scripts/beets_metadata_refresh.py")
        
    def _run_refresh(self, quick: bool = False):
        """Execute the metadata refresh script."""
        try:
            cmd = ["python3", str(self.script_path)]
            if quick:
                cmd.append("--quick")
            
            logger.info(f"[METADATA REFRESH] Starting {'quick' if quick else 'full'} refresh...")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                logger.info("[METADATA REFRESH] Completed successfully")
            else:
                logger.warning(f"[METADATA REFRESH] Exited with code {result.returncode}")
                if result.stderr:
                    logger.error(f"[METADATA REFRESH] Error: {result.stderr[:500]}")
                    
        except Exception as e:
            logger.error(f"[METADATA REFRESH] Error running refresh: {e}")
    
    def _time_until_next_daily_run(self) -> int:
        """Calculate seconds until next daily run."""
        now = datetime.now()
        hour, minute = map(int, self.refresh_time.split(':'))
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        # If target time has passed today, schedule for tomorrow
        if target <= now:
            target = target.replace(day=target.day + 1)
        
        delta = target - now
        return int(delta.total_seconds())
    
    def _daily_loop(self):
        """Daily refresh loop - runs at specific time each day."""
        logger.info(f"[METADATA REFRESH] Daily mode - will run at {self.refresh_time}")
        
        while self.running:
            # Calculate time until next run
            sleep_seconds = self._time_until_next_daily_run()
            logger.info(f"[METADATA REFRESH] Next run in {sleep_seconds / 3600:.1f} hours")
            
            # Sleep until run time (check every 60 seconds to allow shutdown)
            for _ in range(sleep_seconds // 60):
                if not self.running:
                    return
                time.sleep(60)
            
            # Final sleep for remaining seconds
            if self.running:
                time.sleep(sleep_seconds % 60)
            
            # Run the refresh
            if self.running:
                self._run_refresh(quick=False)
    
    def _interval_loop(self):
        """Interval-based loop - runs every X hours."""
        logger.info(f"[METADATA REFRESH] Interval mode - running every {self.interval_hours} hours")
        
        while self.running:
            # Run the refresh
            self._run_refresh(quick=True)  # Use quick refresh for frequent runs
            
            # Wait for interval
            sleep_seconds = self.interval_hours * 3600
            logger.info(f"[METADATA REFRESH] Next run in {self.interval_hours} hours")
            
            # Sleep in chunks to allow shutdown
            for _ in range(sleep_seconds // 60):
                if not self.running:
                    return
                time.sleep(60)
    
    def start(self):
        """Start the scheduler in a background thread."""
        if self.running:
            logger.warning("[METADATA REFRESH] Already running")
            return
        
        self.running = True
        
        # Choose the appropriate loop based on mode
        if self.mode == "daily":
            target = self._daily_loop
        else:
            target = self._interval_loop
        
        self.thread = threading.Thread(
            target=target,
            daemon=True,
            name="MetadataRefreshScheduler"
        )
        self.thread.start()
        
        logger.info(f"[METADATA REFRESH] Started in {self.mode.upper()} mode")
    
    def stop(self):
        """Stop the scheduler."""
        if not self.running:
            return
            
        logger.info("[METADATA REFRESH] Stopping...")
        self.running = False
        
        if self.thread:
            self.thread.join(timeout=5)
        
        logger.info("[METADATA REFRESH] Stopped")
    
    def run_now(self, quick: bool = False):
        """Manually trigger a refresh immediately (non-blocking)."""
        logger.info(f"[METADATA REFRESH] Manual trigger requested ({'quick' if quick else 'full'})")
        t = threading.Thread(target=lambda: self._run_refresh(quick), daemon=True)
        t.start()
    
    def get_status(self) -> dict:
        """Get current scheduler status."""
        status = {
            "running": self.running,
            "mode": self.mode,
            "thread_alive": self.thread.is_alive() if self.thread else False
        }
        
        if self.mode == "daily":
            status["refresh_time"] = self.refresh_time
            if self.running:
                status["next_run_in_hours"] = self._time_until_next_daily_run() / 3600
        else:
            status["interval_hours"] = self.interval_hours
        
        return status


# Singleton instance
_metadata_scheduler = None

def get_metadata_scheduler(
    mode: str = "daily",
    refresh_time: str = "03:00",
    interval_hours: int = 6
) -> MetadataRefreshScheduler:
    """
    Get or create the global metadata refresh scheduler instance.
    
    Args:
        mode: "daily" (run at specific time) or "interval" (run every X hours)
        refresh_time: Time for daily refresh (HH:MM format, 24-hour)
        interval_hours: Hours between runs (for interval mode)
    """
    global _metadata_scheduler
    if _metadata_scheduler is None:
        _metadata_scheduler = MetadataRefreshScheduler(
            mode=mode,
            refresh_time=refresh_time,
            interval_hours=interval_hours
        )
    return _metadata_scheduler