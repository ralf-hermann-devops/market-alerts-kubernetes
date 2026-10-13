# Kubernetes monitoring

The Kubernetes bootstrap installs kube-prometheus-stack, which provides Prometheus, Grafana, and Kubernetes metrics collection. The application exposes Prometheus metrics from its API, and the base manifests include a Grafana dashboard ConfigMap. Apply the application overlay after installing the charts for the dashboard to be discovered.

## Open Grafana

Forward Grafana's service to localhost:

```bash
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80
```

Open [http://localhost:3000](http://localhost:3000). The default chart credentials can be retrived in a base64 encoded fromat from the secret `kube-prometheus-stack-grafana` in the `monitoring` namespace. Change the password before using the stack in a shared cluster.

Select **Market Alerts API** from the dashboards list. It contains:

- **Webhook request rate by status:** requests per second, grouped by HTTP response code.
- **Webhook p95 latency:** estimated 95th-percentile request duration, aggregated across API replicas.
- **Redis Stream backlog:** unread entries and delivered-but-unacknowledged entries.
- **Redis oldest outstanding message age:** age of the oldest unread or unacknowledged entry.

The panels use data from Prometheus. The dashboard definition lives in `k8s/manifests/base/monitoring/api-dashboard.json`, and Kustomize packages it into a labeled ConfigMap for Grafana's dashboard sidecar to discover.

## Inspect Prometheus

To open Prometheus directly:

```bash
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090
```

Visit [http://localhost:9090/targets](http://localhost:9090/targets) to check that the application metrics target is **UP**, or open [http://localhost:9090/graph](http://localhost:9090/graph) to run PromQL queries.

For example, show webhook requests per second grouped by status:

```promql
sum by (status) (rate(http_requests_total{path="/webhook/tradingview"}[5m]))
```

Estimate webhook p95 latency:

```promql
histogram_quantile(
  0.95,
  sum by (le) (
    rate(http_request_duration_seconds_bucket{path="/webhook/tradingview"}[5m])
  )
)
```

The `[5m]` range is the rate calculation window. Increase it, for example to `[20m]`, when request volume is low or when inspecting a longer period.

The Redis pod's exporter sidecar reports consumer-group lag, pending entries, and the age of the oldest outstanding message independently of worker processing. This prevents slow worker processing from delaying the Redis metrics refresh. Verify the `redis-metrics` target is **UP** on Prometheus's Targets page.
