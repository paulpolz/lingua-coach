# Local monitoring stack

Monitoring services in the repo root `docker-compose.yml`. They start with the app.

```bash
docker compose up
```

| Path | Purpose |
|------|---------|
| `prometheus.yml` | Scrapes `backend:8000/metrics` |
| `loki-config.yml` | Single-process Loki |
| `promtail-config.yml` | Docker log shipping → Loki |
| `grafana/provisioning/` | Datasources + dashboard JSON |

See [`apps/README.md`](../../apps/README.md) and [deployment.md](../../docs/mvp/init/tech_requirements/deployment.md).
