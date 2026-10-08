import logging
import os
import time

from .fetcher import main

INTERVAL_SECONDS = 5 * 60


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)



def run_scheduler():
    while True:
        try:
            main()
        except Exception:
            logger.exception("Fetcher run failed")
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    run_scheduler()
