import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
import redis
from fastapi.testclient import TestClient


def make_client(monkeypatch):
    monkeypatch.setenv("REDIS_HOST", "localhost")
    monkeypatch.setenv("REDIS_PORT", "6379")
    monkeypatch.setenv("REDIS_DB", "0")
    monkeypatch.setenv("REDIS_PASSWORD", "test-password")
    monkeypatch.setenv("WEBHOOK_SECRET", "dev-secret")

    class FakeRedis:
        def xadd(self, *args, **kwargs):
            return "1-0"

        def ping(self):
            return True

    monkeypatch.setattr(
        redis,
        "Redis",
        lambda **kwargs: FakeRedis(),
    )

    api = importlib.import_module("app.main")
    importlib.reload(api)
    return TestClient(api.app)


def test_healthz(monkeypatch):
    client = make_client(monkeypatch)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_webhook_accepts_valid_alert(monkeypatch, caplog):
    caplog.set_level("INFO", logger="app.main")
    client = make_client(monkeypatch)
    response = client.post(
        "/webhook/tradingview",
        json={
            "secret": "dev-secret",
            "symbol": "AAPL",
            "action": "long",
            "price": 123.45,
            "timeframe": "1h",
        },
    )
    assert response.status_code == 202
    assert response.json() == {"status": "queued"}
    assert "Queued webhook" in caplog.text
    assert "dev-secret" not in caplog.text


def test_webhook_rejects_invalid_secret(monkeypatch, caplog):
    caplog.set_level("INFO", logger="app.main")
    client = make_client(monkeypatch)
    response = client.post(
        "/webhook/tradingview",
        json={
            "secret": "wrong-secret",
            "symbol": "AAPL",
            "action": "long",
        },
    )
    assert response.status_code == 401
    assert "Rejected webhook with invalid secret" in caplog.text
    assert "wrong-secret" not in caplog.text


def test_metrics_reports_request_count_latency_and_errors(monkeypatch):
    client = make_client(monkeypatch)
    client.post(
        "/webhook/tradingview",
        json={
            "secret": "dev-secret",
            "symbol": "AAPL",
            "action": "long",
        },
    )
    client.post(
        "/webhook/tradingview",
        json={
            "secret": "wrong-secret",
            "symbol": "AAPL",
            "action": "long",
        },
    )

    response = client.get("/metrics")
    metrics = response.text

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert (
        'http_requests_total{method="POST",path="/webhook/tradingview",status="202"} 1.0'
        in metrics
    )
    assert (
        'http_requests_total{method="POST",path="/webhook/tradingview",status="401"} 1.0'
        in metrics
    )
    assert (
        'http_request_duration_seconds_count{method="POST",path="/webhook/tradingview"} 2.0'
        in metrics
    )
    assert (
        'http_request_duration_seconds_bucket{le="0.001",method="POST",path="/webhook/tradingview"}'
        in metrics
    )
    assert (
        'http_request_duration_seconds_bucket{le="0.003",method="POST",path="/webhook/tradingview"}'
        in metrics
    )
    assert 'path="/metrics"' not in metrics


if __name__ == "__main__":
    # pytest.main(...) returns success or failure but doesnt propagate
    # it as an exit code on its own
    raise SystemExit(pytest.main([__file__]))
