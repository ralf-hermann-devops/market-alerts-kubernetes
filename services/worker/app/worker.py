# services/worker/main.py
import json
import logging
import math
import os
import signal
import socket
import time
from typing import Any, cast

import psycopg
import redis

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

CPU_LOAD_SECONDS = float(os.getenv("WORKER_CPU_LOAD_SECONDS", "0"))
if not math.isfinite(CPU_LOAD_SECONDS) or CPU_LOAD_SECONDS < 0:
    raise ValueError("WORKER_CPU_LOAD_SECONDS must be a finite, non-negative number or not set at all.")

"""
If WORKER_CPU_LOAD_SECONDS exceeds the pods termination grace period, 
simulate_cpu_load continues after SIGTERM. The pod can then be killed 
before the database commit and xack. The alert remains pending, while 
this worker reads only new messages with >. Bound the load to the available 
shutdown time or stop it on SIGTERM, and provide a path to recover pending alerts.
"""
def simulate_cpu_load(duration_seconds: float) -> None:
    """Busy-wait for the requested seconds of monotonic elapsed time.

    Nonpositive durations skip the work. The worker's SIGTERM handler does not
    interrupt this wait.
    """
    deadline = time.monotonic() + duration_seconds
    value = 0
    while time.monotonic() < deadline:
        value = (value * 6364136223846793005 + 1) & 0xFFFFFFFFFFFFFFFF  # keep number in 64 bit boundries to not consume too much memory

def main():
    """Consume new Redis Stream alerts and persist them to PostgreSQL.

    Read connection settings from the environment and use the hostname as the
    consumer name. Ignore duplicate stream IDs on insertion and acknowledge each
    message only after committing it. Pending messages are not reclaimed.

    Suppress Redis ResponseError during group creation. Configuration, connection,
    and message processing errors otherwise propagate, stopping the worker.
    """
    # Listen for a SIGTERM signal and shutdown gracefully in case of one being set
    running = True
    signal.signal(signal.SIGTERM, lambda *_: locals().update(running=False))

    r = redis.Redis(
        host=os.environ["REDIS_HOST"],
        port=int(os.environ["REDIS_PORT"]),
        db=int(os.environ["REDIS_DB"]),
        password=os.environ["REDIS_PASSWORD"],
        decode_responses=True,
    )

    stream_name = os.getenv("REDIS_STREAM", "alerts")
    group = os.getenv("REDIS_GROUP", "workers")
    consumer = socket.gethostname()   # pod name = unique consumer
    logger.info("Starting worker consumer=%s stream=%s group=%s",
        consumer, stream_name, group)
    try:
        r.xgroup_create(stream_name, group, id="0", mkstream=True)
    except redis.ResponseError:
        pass  # group exists
    logger.info("Redis consumer group is ready")


    logger.info("Connecting to PostgreSQL host=%s", os.environ["POSTGRES_HOST"])
    with psycopg.connect(
            dbname=os.environ["POSTGRES_DB"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            host=os.environ["POSTGRES_HOST"],
            port=os.environ["POSTGRES_PORT"]) as db:
        logger.info("Connected to PostgreSQL; waiting for alerts")
        while running:
            stream_messages = cast(list[Any], r.xreadgroup(group, consumer, {stream_name: ">"}, count=10, block=5000) or [])
            for _, msgs in stream_messages:
                for msg_id, fields in msgs:
                    try:
                        a = json.loads(fields["payload"])
                        logger.info("Processing alert stream_id=%s symbol=%s action=%s",
                            msg_id, a.get("symbol", "unknown"), a.get("action", "unknown"))

                        
                        simulate_cpu_load(CPU_LOAD_SECONDS)

                        db.execute(
                            "INSERT INTO alerts (stream_id, symbol, action, price, timeframe) "
                            "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (stream_id) DO NOTHING",
                            (msg_id, a["symbol"], a["action"], a.get("price"), a.get("timeframe")))
                        db.commit()
                        r.xack(stream_name, group, msg_id)      # ack only after the DB commit

                    except Exception:
                        logger.exception("Failed processing alert stream_id=%s", msg_id)
                        raise
                    logger.info("Processed and acknowledged alert " \
                                "stream_id=%s symbol=%s action=%s price=%s timeframe=%s",
                            msg_id, a["symbol"], a["action"], a.get("price"), a.get("timeframe"))

    logger.info("Worker shut down")

if __name__ == "__main__":
    main()
