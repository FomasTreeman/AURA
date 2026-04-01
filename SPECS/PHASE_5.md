**📜 Phase 5 Technical Specification: UI, Observability & GreenOps**
*(Real-time Streaming UI, Metrics, Dashboards, Carbon-aware Scheduling)*

Phase 5 builds the developer-facing and operator-facing surfaces: a streaming web UI, monitoring, and sustainability tooling.

Goal: Provide a Next.js streaming UI for queries and node status, Prometheus metrics + Grafana dashboards, and carbon-aware scheduling utilities.

Success Criteria
- Full-featured UI that streams LLM outputs via SSE and shows peer status, query traces, and citation lists.
- Prometheus-compatible `/metrics` endpoints and a Grafana dashboard shipped as JSON.
- Carbon/SCI metric reporting and a scheduler that can defer non-urgent tasks to low-carbon windows.

Frontend Stack
- Next.js 15 (App Router), Tailwind CSS, Server-Sent Events (SSE) for streaming.
- Pages/components:
  - `/` : query box + streaming answer area with sources panel.
  - `/peers` : peer map with connectivity, latency, and model-manifest versions.
  - `/metrics` : simplified embedded Grafana panel.

Backend changes
- Add SSE endpoint `GET /stream/query/{query_id}` that streams tokens as JSON lines with incremental citation attachments.
- Add `/metrics` Prometheus exporter (use `prometheus_client` Python library).

Exact Setup Commands (local)
```bash
# frontend
cd frontend
pnpm install
pnpm dev

# backend
uvicorn backend.main:app --port 8000
```

Observability
- Expose metrics: aura_queries_total, aura_query_duration_seconds, aura_peers_connected, cpu_usage_percent, memory_usage_bytes, carbon_estimate_grams.
- Provide Grafana dashboard JSON in `docs/grafana/dashboard.json`.

GreenOps
- Integrate `codecarbon` or grid-intensity API; schedule heavy tasks (e.g., re-indexing) to run when grid intensity < threshold.
- Provide CLI: `aura schedule --task reindex --when low-carbon` (uses local policy + grid API check).

Testing
- UI e2e tests (Playwright): streaming accuracy, citation UI updates, peer status updates.
- Metrics tests: ensure counters increment on queries and errors.

Deliverables
- `frontend/` Next.js app, `/metrics` exporter, Grafana dashboard, Playwright tests, and a sample `docker-compose.frontend.yml` for local demo.
