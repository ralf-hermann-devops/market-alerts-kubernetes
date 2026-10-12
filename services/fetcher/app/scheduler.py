"""
Since Docker Compose doesn't have build in scheduling like Kubernetes' ChonJob
it will use this small script to call the fetcher on a schedule.
"""

import logging
import os
import signal
import time

from .fetcher import main

INTERVAL_SECONDS = 5 * 60
SIGTERM_RECHECK_SECONDS = 10

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

running = True
signal.signal(signal.SIGTERM, lambda *_: globals().update(running=False))

def run_scheduler():
    last_time = time.monotonic() - INTERVAL_SECONDS
    while running:
        if time.monotonic() > last_time + INTERVAL_SECONDS:
            try:
                main()
            except Exception:
                logger.exception("Fetcher run failed")        
            finally:
                last_time = time.monotonic()
        time.sleep(SIGTERM_RECHECK_SECONDS)


if __name__ == "__main__":
    run_scheduler()
