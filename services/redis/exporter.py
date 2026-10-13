import logging
import math
import os
import time
from typing import Any, cast

import redis
from prometheus_client import Counter, Gauge, start_http_server

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

STREAM_LAG = Gauge(
    "market_alerts_redis_stream_group_lag",
    "Unread Redis Stream entries for the consumer group.",
    ("stream", "group"),
)
STREAM_LAG_AVAILABLE = Gauge(
    "market_alerts_redis_stream_group_lag_available",
    "Whether Redis can calculate consumer-group lag.",
    ("stream", "group"),
)
STREAM_PENDING = Gauge(
    "market_alerts_redis_stream_pending",
    "Redis Stream entries delivered to consumers but not acknowledged.",
    ("stream", "group"),
)
STREAM_OLDEST_AGE = Gauge(
    "market_alerts_redis_stream_oldest_outstanding_age_seconds",
    "Age of the oldest unread or pending Redis Stream entry.",
    ("stream", "group"),
)
STREAM_COLLECTION_ERRORS = Counter(
    "market_alerts_redis_stream_metrics_collection_errors_total",
    "Redis Stream metrics collection failures.",
    ("stream", "group"),
)
STREAM_COLLECTION_SUCCESS = Gauge(
    "market_alerts_redis_stream_metrics_collection_success",
    "Whether the most recent Redis Stream metrics collection succeeded.",
    ("stream", "group"),
)


def collect_stream_metrics(
    client: redis.Redis,
    stream_name: str,
    group_name: str,
    current_time: float | None = None,
) -> tuple[int | None, int, float]:
    """Return unread lag, pending entries, and oldest outstanding age."""
    groups = cast(list[dict[str, Any]], client.xinfo_groups(stream_name))
    group_info = next(
        (item for item in groups if item["name"] == group_name),
        None,
    )
    if group_info is None:
        raise redis.ResponseError(
            f"Consumer group {group_name!r} is missing from stream {stream_name!r}"
        )

    pending_summary = cast(dict[str, Any], client.xpending(stream_name, group_name))
    pending_count = int(pending_summary["pending"])
    outstanding_ids = []
    if pending_summary["min"] is not None:
        outstanding_ids.append(pending_summary["min"])

    unread_entries = cast(
        list[tuple[str, dict[str, str]]],
        client.xrange(
            stream_name,
            min=f"({group_info['last-delivered-id']}",
            max="+",
            count=1,
        ),
    )
    if unread_entries:
        outstanding_ids.append(unread_entries[0][0])

    if not outstanding_ids:
        oldest_age_seconds = 0.0
    else:
        oldest_id = min(
            outstanding_ids,
            key=lambda entry_id: tuple(int(part) for part in entry_id.split("-", 1)),
        )
        timestamp = int(oldest_id.split("-", 1)[0]) / 1000
        now = time.time() if current_time is None else current_time
        oldest_age_seconds = max(0.0, now - timestamp)

    lag_value = group_info["lag"]
    lag = None if lag_value is None else int(lag_value)
    return lag, pending_count, oldest_age_seconds


def refresh_metrics(
    client: redis.Redis,
    stream_name: str,
    group_name: str,
) -> None:
    labels = (stream_name, group_name)
    try:
        lag, pending_count, oldest_age_seconds = collect_stream_metrics(
            client,
            stream_name,
            group_name,
        )
    except redis.RedisError:
        STREAM_COLLECTION_ERRORS.labels(*labels).inc()
        STREAM_COLLECTION_SUCCESS.labels(*labels).set(0)
        logger.exception("Failed collecting Redis Stream metrics")
        return

    STREAM_LAG_AVAILABLE.labels(*labels).set(lag is not None)
    STREAM_LAG.labels(*labels).set(float("nan") if lag is None else lag)
    STREAM_PENDING.labels(*labels).set(pending_count)
    STREAM_OLDEST_AGE.labels(*labels).set(oldest_age_seconds)
    STREAM_COLLECTION_SUCCESS.labels(*labels).set(1)


def main() -> None:
    stream_name = os.getenv("REDIS_STREAM", "alerts")
    group_name = os.getenv("REDIS_GROUP", "workers")
    metrics_port = int(os.getenv("METRICS_PORT", "8001"))
    collection_interval = float(os.getenv("COLLECTION_INTERVAL_SECONDS", "5"))
    if not math.isfinite(collection_interval) or collection_interval <= 0:
        raise ValueError("COLLECTION_INTERVAL_SECONDS must be a positive number")

    client = redis.Redis(
        host=os.getenv("REDIS_HOST", "127.0.0.1"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=int(os.getenv("REDIS_DB", "0")),
        password=os.environ["REDIS_PASSWORD"],
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )

    start_http_server(metrics_port)
    logger.info(
        "Redis Stream metrics available on port %s for stream=%s group=%s",
        metrics_port,
        stream_name,
        group_name,
    )
    while True:
        refresh_metrics(client, stream_name, group_name)
        time.sleep(collection_interval)


if __name__ == "__main__":
    main()
