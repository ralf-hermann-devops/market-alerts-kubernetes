# services/api/main.py
import os, json, redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()
r = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
stream_name = os.getenv("REDIS_STREAM", "alerts")

class Alert(BaseModel):
    secret: str          # TradingView can't send custom headers, so put it in the JSON body
    symbol: str
    action: str          # e.g. "long", "short", "close"
    price: float | None = None
    timeframe: str | None = None

@app.post("/webhook/tradingview", status_code=202)
def webhook(alert: Alert):
    if alert.secret != os.environ["WEBHOOK_SECRET"]:
        raise HTTPException(401)
    r.xadd(stream_name, {"payload": alert.model_dump_json(exclude={"secret"})},
           maxlen=100_000, approximate=True)
    return {"status": "queued"}

@app.get("/healthz")
def healthz(): return {"ok": True}

@app.get("/readyz")
def readyz():
    r.ping()             # raises -> 500 -> pod removed from Service
    return {"ready": True}