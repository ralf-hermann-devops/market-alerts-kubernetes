# services/worker/main.py
import json
import os
import signal
import socket
from typing import Any, cast

import psycopg
import redis

running = True
signal.signal(signal.SIGTERM, lambda *_: globals().update(running=False))

r = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
stream_name = os.getenv("REDIS_STREAM", "alerts")
group = os.getenv("REDIS_GROUP", "workers")
consumer = socket.gethostname()   # pod name = unique consumer
try:
    r.xgroup_create(stream_name, group, id="0", mkstream=True)
except redis.ResponseError: pass                     # group exists

with psycopg.connect(os.environ["DATABASE_URL"]) as db:
    while running:
        stream_messages = cast(list[Any], r.xreadgroup(group, consumer, {stream_name: ">"}, count=10, block=5000) or [])
        for _, msgs in stream_messages:
            for msg_id, fields in msgs:
                a = json.loads(fields["payload"])
                db.execute(
                    "INSERT INTO alerts (stream_id, symbol, action, price, timeframe) "
                    "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (stream_id) DO NOTHING",
                    (msg_id, a["symbol"], a["action"], a.get("price"), a.get("timeframe")))
                db.commit()
                r.xack(stream_name, group, msg_id)      # ack only after the DB commit