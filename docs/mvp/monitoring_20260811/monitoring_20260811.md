# Monitoring Development Requirements

### 1. API monitoring
- Add Prometheus instrumentation to FastAPI.
- Track total API requests, response codes, and request latency.
- Expose `/metrics` endpoint.
- Log failed requests as structured JSON, including request ID, endpoint, status code, duration, and error.

### 2. LLM monitoring
- Instrument all Gemini API calls.
- Track:
  - Number of LLM requests
  - Input/output/total tokens
  - LLM latency
  - LLM errors and timeouts
  - Retries
  - Token/context limit violations
- Add custom Prometheus metrics for LLM usage.

### 3. Monitoring infrastructure
- Deploy **Prometheus** for metrics collection and storage.
- Deploy **Loki** for log collection and storage.
- Deploy **Grafana** for dashboards and visualization.
- Keep monitoring data separate from the application's PostgreSQL database.

### 4. Dashboards
Create Grafana dashboards for:
- API request volume and response-code distribution
- API error rate and P95/P99 latency
- LLM request volume and token consumption
- LLM errors, retries, and latency
- Infrastructure health

### 5. Local & production deployment
- Run FastAPI, PostgreSQL, Prometheus, Loki, and Grafana as separate services locally, preferably with Docker Compose.
- Use the same service architecture in production; services may initially run on the same server and be separated as the system scales.

### 6. Future: AI quality monitoring
Add a separate evaluation layer to measure tutor/agent quality and accuracy. This should be treated separately from infrastructure monitoring.

---

## Implementation status (MVP)

| Area | Local | Production (Railway + Vercel) |
|------|-------|-------------------------------|
| Structured JSON logs + `X-Request-ID` | Yes | Yes (stdout → Railway log search) |
| Prometheus `/metrics` + LLM metrics | Yes | Exposed on API; scrape deferred |
| Grafana + Loki + Prometheus stack | Docker Compose `--profile monitoring` | **Not deployed** (cost); use Railway logs |
| Client error telemetry | `POST /api/v1/telemetry/client-errors` | Same endpoint; logs land in Railway |

### Local setup

```bash
# App only
docker compose up

# App + Prometheus (:9090) + Loki (:3100) + Grafana (:3001)
docker compose --profile monitoring up
```

- Grafana: http://localhost:3001 (anonymous Viewer, or `admin` / `admin`)
- Prometheus targets: http://localhost:9090/targets
- Raw metrics: `curl http://localhost:8000/metrics`
- Correlate a failure: copy `X-Request-ID` from browser Network tab → Grafana → **Errors & Correlation** dashboard → `request_id` textbox, or Loki Explore:
  ```
  {service="backend"} | json | request_id="<uuid>"
  ```

Config lives under [`infra/monitoring/`](../../infra/monitoring/).

### Production runbook (no Grafana yet)

Same JSON log schema locally and on Railway. Useful filters in Railway logs:

| Goal | Filter / search |
|------|-----------------|
| User-reported bug | Ask for / copy `X-Request-ID` → search that UUID |
| API failures | `"event":"http_request"` and `"status_code":5` or `level":"ERROR"` |
| Token burn | `"event":"llm_call"` — sum `input_tokens` / `output_tokens` over the window |
| LLM timeouts / API errors | `"event":"llm_call"` and `"status":"error"` (see `error_type`) |
| Frontend failures | `"event":"client_error"` |
| Silent DB write issues | `"event":"db_persist_failed"` |
| Lesson job failures | `"event":"lesson_generation_failed"` or `"request_id":"<job_id>"` |

**Note:** `/metrics` is unauthenticated for local scrape. Before pointing a public scraper (e.g. Grafana Cloud) at production, put metrics behind network restriction or auth.

### Optional next step: Grafana Cloud free tier

When you want prod dashboards without self-hosting three services on Railway:

1. Create a Grafana Cloud free account
2. Run Grafana Agent / Alloy on Railway (or use Grafana Cloud's hosted Prometheus remote_write from a tiny sidecar)
3. Scrape `https://api.<domain>/metrics` (or private network) and ship JSON logs
4. Reuse the dashboard JSON under `infra/monitoring/grafana/provisioning/dashboards/json/`

Until then, Railway log search + the local Grafana profile is enough for MVP debugging.
