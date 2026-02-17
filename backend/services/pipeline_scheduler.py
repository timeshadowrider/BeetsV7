# backend/services/pipeline_scheduler.py
"""
Continuous Pipeline Scheduler for BeetsV7
Runs the pipeline in a continuous loop - starts again immediately after completion.
Also supports interval-based scheduling.
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
        """Check if the pipeline is currently running via lock file."""
        return self.lock_file.exists()
    
    def _run_pipeline(self):
        """Execute the pipeline controller script."""
        try:
            logger.info(f"[SCHEDULER] Starting pipeline run at {datetime.now()}")
            
            # Run the pipeline
            result = subprocess.run(
                ["python3", "/app/scripts/pipeline_controller_v7.py"],
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                logger.info("[SCHEDULER] Pipeline completed successfully")
            else:
                logger.warning(f"[SCHEDULER] Pipeline exited with code {result.returncode}")
                if result.stderr:
                    logger.warning(f"[SCHEDULER] Error output: {result.stderr[:500]}")
                    
        except Exception as e:
            logger.error(f"[SCHEDULER] Error running pipeline: {e}")
    
    def _continuous_loop(self):
        """
        Continuous loop mode - runs pipeline again immediately after completion.
        Includes a small delay to prevent CPU spinning.
        """
        logger.info("[SCHEDULER] Starting CONTINUOUS loop mode")
        
        while self.running:
            # Wait for any existing pipeline run to complete
            if self._is_pipeline_running():
                logger.debug("[SCHEDULER] Pipeline already running, waiting...")
                time.sleep(30)  # Check every 30 seconds
                continue
            
            # Run the pipeline
            self._run_pipeline()
            
            # Small delay before checking again (prevents CPU spinning)
            # This gives time for lock file cleanup and prevents immediate re-trigger
            if self.running:
                time.sleep(10)  # 10 second cooldown
    
    def _interval_loop(self):
        """
        Interval-based mode - waits X minutes between runs.
        """
        logger.info(f"[SCHEDULER] Starting INTERVAL mode (every {self.interval_minutes} minutes)")
        
        while self.running:
            # Run the pipeline
            self._run_pipeline()
            
            # Wait for the interval
            if self.running:
                logger.info(f"[SCHEDULER] Waiting {self.interval_minutes} minutes until next run...")
                time.sleep(self.interval_minutes * 60)
    
    def start(self):
        """Start the scheduler in a background thread."""
        if self.running:
            logger.warning("[SCHEDULER] Already running")
            return
        
        self.running = True
        
        # Choose the appropriate loop based on mode
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
