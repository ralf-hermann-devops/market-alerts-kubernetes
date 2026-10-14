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
    buckets=(
        0.0005,
        0.001,
        0.002,
        0.003,
        0.005,
        0.0075,
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1.0,
        2.5,
        5.0,
        10.0,
    ),
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
    call_next: RequestResponseEndpoint) -> Response:
    """Return the downstream response while counting and timing non-metrics requests.

    Record elapsed seconds until call_next returns or raises, using the matched
    route template or "unmatched" as the path label. Downstream exceptions
    propagate after being counted with status 500. Requests to /metrics bypass
    instrumentation.
    """
    
    # Exclude the metrics endpoint to avoid monitoring its own requests.    
    if request.url.path == "/metrics":
        return await call_next(request)

    start_time = time.perf_counter()
    status_code = 500

    allowed_method_routes = {
        ("POST", "/webhook/tradingview"),
    }

    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        # Resolve the matched route after call_next, since routing may not
        # have happened before it. Use the route template, not the raw URL,
        # to avoid creating separate metrics for variable path parameters.
        # Templates are not in use yet but this best practice is implemented
        # in case this changes later
        route = request.scope.get("route")
        path = route.path if route is not None else "unmatched"
        method = request.method

        # Normalize unexpected method/path combinations to limit metric
        # cardinality and prevent unbounded memory usage from too many 
        # recived unique labels (accidental or intentionally malicious)
        if (method, path) not in allowed_method_routes:
            method = "OTHER"
            path = "INVALID"
        http_requests.labels(method, path, str(status_code)).inc()
        http_request_duration.labels(method, path).observe(
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
    """Return the API's metrics registry in Prometheus text exposition format."""
    return Response(
        content=generate_latest(metrics_registry),
        media_type=CONTENT_TYPE_LATEST,
    )
