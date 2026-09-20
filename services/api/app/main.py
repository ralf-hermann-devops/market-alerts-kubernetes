# services/api/main.py
import logging
import os

import redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI()
r = redis.Redis(
    host=os.environ["REDIS_HOST"],
    port=int(os.environ["REDIS_PORT"]),
    db=int(os.environ["REDIS_DB"]),
    password=os.environ["REDIS_PASSWORD"],
    decode_responses=True,
)
stream_name = os.getenv("REDIS_STREAM", "alerts")
logger.info("API configured; Redis stream=%s", stream_name)

class Alert(BaseModel):
    secret: str          # TradingView can't send custom headers, so put it in the JSON body
    symbol: str
    action: str          # e.g. "long", "short", "close"
    price: float | None = None
    timeframe: str | None = None


@app.post("/webhook/tradingview", status_code=202)
def webhook(alert: Alert):
    if alert.secret != os.environ["WEBHOOK_SECRET"]:
        logger.warning(
            "Rejected webhook with invalid secret symbol=%s action=%s",
            alert.symbol,
            alert.action,
        )
        raise HTTPException(401)
    try:
        stream_id = r.xadd(
            stream_name,
            {"payload": alert.model_dump_json(exclude={"secret"})},
            maxlen=100_000,
            approximate=True,
        )
    except redis.RedisError:
        logger.exception(
            "Could not queue webhook symbol=%s action=%s",
            alert.symbol,
            alert.action,
        )
        raise
    logger.info(
        "Queued webhook stream_id=%s symbol=%s action=%s",
        stream_id,
        alert.symbol,
        alert.action,
    )
    return {"status": "queued"}


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/readyz")
def readyz():
    try:
        r.ping()
    except redis.RedisError:
        logger.exception("Readiness check failed: Redis is unavailable")
        raise
    return {"ready": True}
