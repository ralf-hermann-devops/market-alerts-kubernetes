from services.redis.exporter import collect_stream_metrics


class FakeRedis:
    def __init__(self, lag: int | None, pending_min: str | None, unread_id: str | None):
        self.lag = lag
        self.pending_min = pending_min
        self.unread_id = unread_id

    def xinfo_groups(self, stream_name: str) -> list[dict[str, object]]:
        return [
            {
                "name": "workers",
                "lag": self.lag,
                "last-delivered-id": "15000-0",
            }
        ]

    def xpending(self, stream_name: str, group_name: str) -> dict[str, object]:
        return {"pending": 2 if self.pending_min else 0, "min": self.pending_min}

    def xrange(
        self,
        stream_name: str,
        min: str,
        max: str,
        count: int,
    ) -> list[tuple[str, dict[str, str]]]:
        if self.unread_id is None:
            return []
        return [(self.unread_id, {"payload": "{}"})]


def test_collects_lag_pending_and_oldest_outstanding_age() -> None:
    client = FakeRedis(lag=8, pending_min="10000-0", unread_id="12000-0")

    assert collect_stream_metrics(client, "alerts", "workers", current_time=20) == (
        8,
        2,
        10,
    )


def test_reports_zero_age_when_no_entries_are_outstanding() -> None:
    client = FakeRedis(lag=0, pending_min=None, unread_id=None)

    assert collect_stream_metrics(client, "alerts", "workers", current_time=20) == (
        0,
        0,
        0,
    )


def test_preserves_unavailable_redis_lag() -> None:
    client = FakeRedis(lag=None, pending_min=None, unread_id=None)

    lag, pending, oldest_age = collect_stream_metrics(
        client,
        "alerts",
        "workers",
        current_time=20,
    )

    assert lag is None
    assert pending == 0
    assert oldest_age == 0
