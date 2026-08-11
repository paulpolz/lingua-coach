# Local monitoring stack

Opt-in Docker Compose profile used by the repo root `docker-compose.yml`.

```bash
docker compose --profile monitoring up
```

| Path | Purpose |
|------|---------|
| `prometheus.yml` | Scrapes `backend:8000/metrics` |
| `loki-config.yml` | Single-process Loki |
| `promtail-config.yml` | Docker log shipping → Loki |
| `grafana/provisioning/` | Datasources + dashboard JSON |

See [`docs/mvp/monitoring_20260811/monitoring_20260811.md`](../../docs/mvp/monitoring_20260811/monitoring_20260811.md) and [`apps/README.md`](../../apps/README.md).
