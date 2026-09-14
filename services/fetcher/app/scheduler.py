import logging
import time

from .fetcher import main


INTERVAL_SECONDS = 5 * 60


def run_scheduler():
    while True:
        try:
            main()
        except Exception:
            logging.exception("Fetcher run failed")
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_scheduler()
