# Feature Spec: Loki Log Aggregation

## Problem

AURA currently has structured logging via `backend/utils/logging.py` but logs are only visible by tailing container stdout. In a multi-node mesh (3+ containers) this means:

- Correlating events across nodes requires opening multiple terminal tabs.
- Logs disappear on container restart.
- There is no way to query logs (e.g. "show all errors from node2 in the last 10 minutes").
- The Grafana dashboard has metrics panels but no log panels — operators must context-switch between Grafana and terminal.

## Solution: Grafana Loki

Add Loki as a log aggregation backend and Promtail as the log shipping agent. This integrates directly into the existing Grafana instance, giving a unified observability surface: metrics (Prometheus) + logs (Loki) in the same dashboard.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ AURA Containers (backend, aura-node2, aura-node3)           │
│                                                             │
│  uvicorn → structured JSON logs → stdout                    │
└────────────────────────┬────────────────────────────────────┘
                         │ Docker log driver
                         ▼
┌────────────────────────────────────────────────────────────┐
│ Promtail                                                   │
│  • reads /var/lib/docker/containers/*/*-json.log           │
│  • labels: {job, container_name, node}                     │
│  • ships to Loki push API                                  │
└────────────────────────┬───────────────────────────────────┘
                         │ HTTP push (port 3100)
                         ▼
┌────────────────────────────────────────────────────────────┐
│ Loki                                                       │
│  • stores log streams indexed by labels                    │
│  • exposes LogQL query API                                 │
└────────────────────────┬───────────────────────────────────┘
                         │ Loki datasource
                         ▼
┌────────────────────────────────────────────────────────────┐
│ Grafana                                                    │
│  • existing Prometheus panels                              │
│  + new Loki log panels (Explore + dashboard rows)          │
└────────────────────────────────────────────────────────────┘
```

## New Services in `docker-compose.frontend.yml`

```yaml
loki:
  image: grafana/loki:2.9.0
  ports:
    - "3100:3100"
  command: -config.file=/etc/loki/loki.yaml
  volumes:
    - ./docs/loki/loki.yaml:/etc/loki/loki.yaml:ro
    - loki_data:/loki
  networks:
    - aura-network

promtail:
  image: grafana/promtail:2.9.0
  command: -config.file=/etc/promtail/promtail.yaml
  volumes:
    - ./docs/loki/promtail.yaml:/etc/promtail/promtail.yaml:ro
    - /var/lib/docker/containers:/var/lib/docker/containers:ro
    - /var/run/docker.sock:/var/run/docker.sock:ro
  networks:
    - aura-network
  depends_on:
    - loki
```

## New Config Files

### `docs/loki/loki.yaml`
Minimal single-process Loki config:
```yaml
auth_enabled: false

server:
  http_listen_port: 3100

ingester:
  lifecycler:
    ring:
      kvstore:
        store: inmemory
      replication_factor: 1
  chunk_idle_period: 5m
  chunk_retain_period: 30s

schema_config:
  configs:
    - from: 2024-01-01
      store: boltdb-shipper
      object_store: filesystem
      schema: v11
      index:
        prefix: index_
        period: 24h

storage_config:
  boltdb_shipper:
    active_index_directory: /loki/index
    cache_location: /loki/index_cache
  filesystem:
    directory: /loki/chunks

limits_config:
  reject_old_samples: true
  reject_old_samples_max_age: 168h

compactor:
  working_directory: /loki/compactor
```

### `docs/loki/promtail.yaml`
Scrapes Docker container logs and labels them by container name:
```yaml
server:
  http_listen_port: 9080

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: aura-containers
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
        refresh_interval: 5s
        filters:
          - name: label
            values: ["com.docker.compose.project"]
    relabel_configs:
      - source_labels: [__meta_docker_container_name]
        target_label: container
      - source_labels: [__meta_docker_container_label_com_docker_compose_service]
        target_label: service
      - replacement: aura
        target_label: job
    pipeline_stages:
      - json:
          expressions:
            level: level
            message: message
            logger: name
      - labels:
          level:
          logger:
```

## Grafana Datasource Provisioning

Add to `docs/grafana/provisioning/datasources/datasources.yaml`:
```yaml
- name: Loki
  type: loki
  access: proxy
  url: http://loki:3100
  isDefault: false
```

## Grafana Dashboard Changes (`docs/grafana/dashboard.json`)

Add a new **Logs** row to the existing dashboard with:

1. **All Node Logs** — LogQL: `{job="aura"}` — shows unified stream from all containers
2. **Errors Only** — LogQL: `{job="aura"} |= "ERROR"` — filtered error stream
3. **Node Selector** — variable `$node` mapped to `container` label — filter by specific node
4. **P2P Events** — LogQL: `{job="aura"} |= "P2P"` — peer connect/disconnect events
5. **Rendezvous Activity** — LogQL: `{job="aura"} |= "Rendezvous"` — discovery heartbeats

## Structured Logging

For Loki to extract useful labels from AURA's existing logs, the backend should emit JSON-structured logs. Current logging uses `rich` (human-readable). Add a JSON formatter for container environments:

Modify `backend/utils/logging.py`:
- If `LOG_FORMAT=json` env var is set, use `logging.Formatter` with JSON output
- Fields: `timestamp`, `level`, `name` (logger name), `message`, `node_id` (peer_id prefix)
- Default remains human-readable for local dev

This lets Promtail's `json` pipeline stage extract `level` and `logger` as Loki labels, enabling queries like: `{job="aura", level="ERROR"}`.

## New Environment Variable

| Env Var | Default | Description |
|---------|---------|-------------|
| `LOG_FORMAT` | `text` | `json` for structured logging (set in Docker compose) |

## Implementation Steps

1. `docs/loki/loki.yaml` — Loki config
2. `docs/loki/promtail.yaml` — Promtail scrape config
3. `docs/grafana/provisioning/datasources/datasources.yaml` — add Loki datasource
4. `docker-compose.frontend.yml` — add `loki` and `promtail` services, add `loki_data` volume, set `LOG_FORMAT=json` on all backend services
5. `backend/utils/logging.py` — add JSON formatter activated by `LOG_FORMAT=json`
6. `docs/grafana/dashboard.json` — add Logs row with LogQL panels

## Acceptance Criteria

- [ ] `docker compose up` brings up Loki and Promtail alongside existing services
- [ ] Grafana → Explore → Loki datasource → `{job="aura"}` returns logs from all 3 nodes
- [ ] Grafana dashboard has a Logs row with at minimum an "All Logs" and "Errors Only" panel
- [ ] `{job="aura", level="ERROR"}` returns only error-level log lines
- [ ] Container restart does not cause log loss (Promtail position tracking resumes)
- [ ] Local dev (`python -m uvicorn`) still uses human-readable logging (LOG_FORMAT=text default)

## Notes

- Loki version pinned to `2.9.0` to match Grafana `10.2.0` compatibility matrix
- Promtail requires read access to Docker socket and container log directory — acceptable for local dev/demo; in production use a dedicated log shipper (Vector, Fluent Bit) with appropriate permissions
- Loki is not a replacement for Prometheus — metrics stay in Prometheus, logs go to Loki; both visible in same Grafana instance
