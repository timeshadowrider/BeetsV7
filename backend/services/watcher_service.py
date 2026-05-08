import subprocess
import threading
import logging

logger = logging.getLogger(__name__)


def start_inbox_settle_watcher():
    """Launch the inbox settle watcher (watcher_v7.py) as a background process."""
    def _run():
        try:
            subprocess.run(
                ["python3", "/app/scripts/watcher_v7.py"],
                check=False,
            )
        except Exception as e:
            logger.error(f"[WATCHER] Inbox settle watcher crashed: {e}")

    t = threading.Thread(target=_run, daemon=True, name="inbox-settle-watcher")
    t.start()
    logger.info("[WATCHER] Inbox settle watcher started")
