# services/worker/main.py
import json
import logging
import os
import signal
import socket
from typing import Any, cast

import psycopg
import redis


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

running = True
signal.signal(signal.SIGTERM, lambda *_: globals().update(running=False))

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
logger.info(
    "Starting worker consumer=%s stream=%s group=%s",
    consumer,
    stream_name,
    group,
)
try:
    r.xgroup_create(stream_name, group, id="0", mkstream=True)
except redis.ResponseError: pass                     # group exists
logger.info("Redis consumer group is ready")

logger.info("Connecting to PostgreSQL host=%s", os.environ["POSTGRES_HOST"])
with psycopg.connect(
    dbname=os.environ["POSTGRES_DB"],
    user=os.environ["POSTGRES_USER"],
    password=os.environ["POSTGRES_PASSWORD"],
    host=os.environ["POSTGRES_HOST"],
    port=os.environ["POSTGRES_PORT"],
) as db:
    logger.info("Connected to PostgreSQL; waiting for alerts")
    while running:
        stream_messages = cast(list[Any], r.xreadgroup(group, consumer, {stream_name: ">"}, count=10, block=5000) or [])
        for _, msgs in stream_messages:
            for msg_id, fields in msgs:
                try:
                    a = json.loads(fields["payload"])
                    logger.info(
                        "Processing alert stream_id=%s symbol=%s action=%s",
                        msg_id,
                        a.get("symbol", "unknown"),
                        a.get("action", "unknown"),
                    )
                    db.execute(
                        "INSERT INTO alerts (stream_id, symbol, action, price, timeframe) "
                        "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (stream_id) DO NOTHING",
                        (msg_id, a["symbol"], a["action"], a.get("price"), a.get("timeframe")))
                    db.commit()
                    r.xack(stream_name, group, msg_id)      # ack only after the DB commit
                except Exception:
                    logger.exception("Failed processing alert stream_id=%s", msg_id)
                    raise
                logger.info(
                    "Processed and acknowledged alert stream_id=%s symbol=%s action=%s price=%s timeframe=%s",
                    msg_id,
                    a["symbol"],
                    a["action"],
                    a.get("price"),
                    a.get("timeframe"),
                )

logger.info("Worker shut down")
