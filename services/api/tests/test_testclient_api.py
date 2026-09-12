import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import redis
from fastapi.testclient import TestClient


def make_client(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("WEBHOOK_SECRET", "dev-secret")

    class FakeRedis:
        def xadd(self, *args, **kwargs):
            return "1-0"

        def ping(self):
            return True

    monkeypatch.setattr(
        redis.Redis,
        "from_url",
        classmethod(lambda cls, *args, **kwargs: FakeRedis()),
    )

    api = importlib.import_module("app.main")
    importlib.reload(api)
    return TestClient(api.app)


def test_healthz(monkeypatch):
    client = make_client(monkeypatch)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_webhook_accepts_valid_alert(monkeypatch):
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


def test_webhook_rejects_invalid_secret(monkeypatch):
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
