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

See [`apps/README.md`](../../apps/README.md) and [deployment.md](../../docs/mvp/init/tech_requirements/deployment.md).
