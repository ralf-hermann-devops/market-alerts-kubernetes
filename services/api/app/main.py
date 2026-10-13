# services/api/main.py
import logging
import os
import time

import redis
from fastapi import FastAPI, HTTPException, Request
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI()
metrics_registry = CollectorRegistry()
http_requests = Counter(
    "http_requests_total",
    "Total number of HTTP requests handled by the API.",
    ["method", "path", "status"],
    registry=metrics_registry,
)
http_request_duration = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["method", "path"],
    registry=metrics_registry,
)
r = redis.Redis(
    host=os.environ["REDIS_HOST"],
    port=int(os.environ["REDIS_PORT"]),
    db=int(os.environ["REDIS_DB"]),
    password=os.environ["REDIS_PASSWORD"],
    decode_responses=True,
)
stream_name = os.getenv("REDIS_STREAM", "alerts")
logger.info("API configured; Redis stream=%s", stream_name)


@app.middleware("http")
async def record_http_metrics(
    request: Request,
    call_next: RequestResponseEndpoint,
) -> Response:
    if request.url.path == "/metrics":
        return await call_next(request)

    start_time = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        path = route.path if route is not None else "unmatched"
        http_requests.labels(request.method, path, str(status_code)).inc()
        http_request_duration.labels(request.method, path).observe(
            time.perf_counter() - start_time
        )


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


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(
        content=generate_latest(metrics_registry),
        media_type=CONTENT_TYPE_LATEST,
    )
