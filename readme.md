# Trading Alerts

This project is a small, containerized backend for collecting and processing trading alerts and market data. A webhook API accepts TradingView alerts, validates a shared secret, and places valid alerts on a Redis stream. A worker consumes the stream and stores alerts in PostgreSQL. A separate fetcher retrieves market candle data and stores it in the same database.

## Project structure

- `services` — application code
    - `services/api/` — webhook API that validates and queues alerts.
    - `services/worker/` — consumes queued alerts and stores them in PostgreSQL.
    - `services/fetcher/` — retrieves market candle data and stores it in PostgreSQL.
    - `services/db/` — database initialization scripts.
- `k8s/` — Kustomize resources for Kubernetes applications and supporting infrastructure.
- `docs/` — project notes and architecture decision records.
    - See [`docs/architecture_decision_records/`](docs/architecture_decision_records/) for decisions about Redis, PostgreSQL, secrets, Kustomize, and staged deployment
    - See [`docs/debugging_note.md`](docs/debugging_note.md) for an overview of how errors encountered during development were investigated and addressed.

## Running locally

Docker Compose starts the API, worker, fetcher, Redis, and PostgreSQL:

```bash
docker compose -f Dockercompose.yaml up --build
```

The API is available at `http://localhost:8000`. Local Compose credentials are for development only; do not use them in shared or production environments.

## Sending TradingView webhook alerts

Send an HTTP `POST` request to `/webhook/tradingview` with a JSON body. The `secret`, `symbol`, and `action` fields are required; `price` and `timeframe` are optional.

```json
{
  "secret": "YOUR_WEBHOOK_SECRET",
  "symbol": "AAPL",
  "action": "long",
  "price": 210.5,
  "timeframe": "5m"
}
```

Set the `secret` to the same value as the API's `WEBHOOK_SECRET`. In TradingView, configure the alert message as this JSON and use the webhook URL for the running API. Supported action examples include `long`, `short`, and `close`.

## Kubernetes

The application is containerized and can also be deployed to a Kubernetes cluster. Kubernetes manifests are organized with Kustomize under `k8s/`, allowing shared configuration to be separated from environment-specific settings. A local cluster such as kind or Minikube can be used for testing, with cloud-specific configuration added when deploying to a platform such as Amazon EKS.
