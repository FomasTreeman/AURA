# Phase 6 Expanded Spec: Test Coverage & Resilience

This document extends `SPECS/PHASE_6.md` with a comprehensive test coverage plan. The original Phase 6 spec covers the resilience features (revocation, manifest gossip, encrypted backup, chaos). This document adds the test strategy needed to deliver those features with confidence, and fills the coverage gaps that exist across all prior phases.

## Current Coverage State (April 2026)

19 test files exist. Significant gaps remain:

| Module | Status |
|--------|--------|
| `rag/generator.py` | **NO TESTS** |
| `rag/federated.py` | Integration only (no unit) |
| `rag/retriever.py` | Indirect only |
| `network/rendezvous.py` | **NO TESTS** |
| `network/registry.py` | **NO TESTS** |
| `observability/greenops.py` | **NO TESTS** |
| `api/sse.py` | **NO TESTS** |
| `ingestion/parser.py` | **NO TESTS** |
| `main.py` (FastAPI app) | **NO TESTS** |
| `cli.py` | **NO TESTS** |
| CI pipeline | **NONE** |

## Part 1: Phase 6 Resilience Features (from original spec)

### 1.1 Revocation & Tombstoning (`backend/resilience/revocation.py`)

**Unit tests** (`tests/test_revocation_unit.py`):
- Tombstone added → persisted in local DB
- Tombstone TTL expiry → entry removed after TTL
- Tombstoned CID → excluded from retrieval results
- Duplicate tombstone → idempotent (no error, no duplicate entry)

**Integration tests** (`tests/integration/test_revocation_propagation.py`):
- 2-node mesh: node1 revokes CID → node2 receives tombstone broadcast within 5s
- Post-revocation: query on node2 does not return tombstoned doc
- Node restart: tombstone persists across restart

### 1.2 Model Manifest Gossip (`backend/resilience/manifest_watcher.py`)

**Unit tests** (`tests/test_manifest_watcher.py`):
- Manifest signing: signature verifies against Ed25519 pubkey
- Manifest verification: tampered manifest detected
- Mismatch policy: "refuse" mode → synthesis blocked; "route" mode → query forwarded

**Integration tests** (`tests/integration/test_manifest_gossip.py`):
- 2-node mesh: nodes exchange manifests on connect
- Mismatch detected: node with wrong model logs warning + applies policy
- Same model: no mismatch, synthesis proceeds normally

### 1.3 Encrypted Backup/Restore (`backend/resilience/backup.py`)

**Unit tests** (`tests/test_backup.py`):
- Backup produces encrypted file (AES-256-GCM)
- Restore decrypts and recreates ChromaDB in target directory
- Wrong passphrase → decryption error raised
- Corrupted backup → integrity error raised

**CLI round-trip test** (`tests/integration/test_backup_roundtrip.py`):
- `backup --out backup.enc --passphrase-file secret.txt`
- Wipe DB
- `backup --restore backup.enc --passphrase-file secret.txt --target ./restored`
- Run Phase 1 acceptance queries against restored DB → results match original

### 1.4 Chaos Suite (`backend/resilience/chaos.py`)

**Chaos scenarios** (`tests/chaos/`):
- `test_peer_churn.py`: repeatedly connect/disconnect nodes; assert mesh re-forms within 60s
- `test_corrupted_vectors.py`: inject corrupted embeddings; assert retrieval degrades gracefully (no crash, error logged)
- `test_network_partition.py`: drop all messages between node1↔node2 for 30s; assert reconnection and state sync after partition heals
- `test_bootstrap_restart.py`: restart the rendezvous node; assert other nodes re-register and maintain connectivity

---

## Part 2: Coverage Gaps from Prior Phases

### 2.1 RAG Layer

**`tests/test_generator.py`** (new):
- `stream_answer()`: mock Ollama client, assert token stream emitted
- `federated_stream_answer()`: with 0 peers → falls back to local; with peers → includes federation metadata
- `check_ollama()`: Ollama unreachable → raises `RuntimeError`

**`tests/test_retriever.py`** (new):
- `retrieve()`: ChromaDB returns results → correctly filtered by score threshold
- Empty collection → returns empty list (no crash)
- Score below threshold → result excluded

**`tests/test_federated_unit.py`** (new, unit-level):
- `FederatedRetriever.query()`: mock adapter with 2 peers → RRF fusion applied to combined results
- Timeout: peer takes >2s → excluded from results, local result returned
- Quorum not met: 0 peers respond → raises/logs appropriately

### 2.2 Network Layer

**`tests/test_rendezvous.py`** (new):
- `MDNSDiscovery`: mock zeroconf, assert service registered + browser started
- `BootstrapDiscovery`: invalid multiaddr → logs error, does not crash; already-connected peer → skipped
- `RendezvousDiscovery._register()`: mock HTTP server, assert POST sent with correct peer_id + multiaddr
- `RendezvousDiscovery._discover()`: mock response with 2 peers → both dialled; self peer_id → skipped
- `RendezvousDiscovery.stop()`: assert unregister HTTP call sent

**`tests/test_registry.py`** (new):
- `register()` + `peers()`: registered entry appears in list
- TTL eviction: entry added with backdated timestamp → not returned by `peers()`
- `unregister()`: entry removed immediately
- Self-exclusion: `peers(exclude_peer_id=x)` does not return x

### 2.3 Observability

**`tests/test_greenops.py`** (new):
- `CarbonTracker.is_low_carbon`: intensity below threshold → True; above → False
- `CarbonAwareScheduler`: critical task → runs immediately regardless of carbon intensity
- `CarbonAwareScheduler`: low-priority task + high intensity → deferred; intensity drops → task runs
- `CarbonAwareScheduler`: `max_defer_hours` exceeded → task runs regardless

**`tests/test_sse.py`** (new):
- `stream_query_sse()`: assert SSE events emitted in order: federation → token(s) → sources → done
- `stream_peer_updates()`: mock adapter with 2 peers → peer event emitted with correct count
- `stream_metrics_updates()`: assert metrics event contains expected fields

### 2.4 API / FastAPI App

**`tests/test_api.py`** (new, using `httpx.AsyncClient` + `TestClient`):
- `GET /health` → 200, ollama status included
- `POST /ingest` → valid dir returns file count + chunk count
- `POST /ingest/upload` → PDF bytes → 200 with chunks_added > 0
- `POST /query` → streaming response, valid NDJSON lines
- `GET /network/status` → adapter running → running: true
- `GET /network/peers` → returns peer list
- `POST /rendezvous/register` → 200; missing fields → 400
- `GET /rendezvous/peers` → returns registered peers
- `DELETE /rendezvous/unregister/{peer_id}` → 200
- `GET /metrics` → Prometheus text format response
- `POST /revoke` → cid tombstoned

### 2.5 Ingestion

**`tests/test_parser.py`** (new):
- Valid single-page PDF → returns list of page text strings
- Corrupted PDF → raises exception or returns empty list (no crash)
- Multi-page PDF → correct page count returned

### 2.6 CLI

**`tests/test_cli.py`** (new):
- `aura ingest <dir>` → exits 0, prints file count
- `aura query "question"` → streams response tokens to stdout
- `aura node status` → prints peer_id and peer count
- `aura backup` → creates encrypted file

---

## Part 3: CI Pipeline

**`.github/workflows/ci.yml`** (new):

```yaml
name: CI
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: pytest tests/ -x --timeout=60 --ignore=tests/chaos
        name: Unit & Integration Tests
      - run: pytest tests/chaos/ --timeout=120
        name: Chaos Tests
        if: github.ref == 'refs/heads/main'

  coverage:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt pytest-cov
      - run: pytest tests/ --cov=backend --cov-report=xml --ignore=tests/chaos
      - uses: codecov/codecov-action@v4
```

**Coverage target**: ≥ 70% line coverage across `backend/` (excluding `backend/__pycache__`).

---

## Deliverables Checklist

### Phase 6 Resilience (original spec)
- [ ] `backend/resilience/revocation.py`
- [ ] `backend/resilience/manifest_watcher.py`
- [ ] `backend/resilience/backup.py`
- [ ] `backend/resilience/chaos.py`
- [ ] `tests/test_revocation_unit.py`
- [ ] `tests/integration/test_revocation_propagation.py`
- [ ] `tests/test_manifest_watcher.py`
- [ ] `tests/integration/test_manifest_gossip.py`
- [ ] `tests/test_backup.py`
- [ ] `tests/integration/test_backup_roundtrip.py`
- [ ] `tests/chaos/test_peer_churn.py`
- [ ] `tests/chaos/test_corrupted_vectors.py`
- [ ] `tests/chaos/test_network_partition.py`
- [ ] `tests/chaos/test_bootstrap_restart.py`

### Coverage Gap Fill
- [ ] `tests/test_generator.py`
- [ ] `tests/test_retriever.py`
- [ ] `tests/test_federated_unit.py`
- [ ] `tests/test_rendezvous.py`
- [ ] `tests/test_registry.py`
- [ ] `tests/test_greenops.py`
- [ ] `tests/test_sse.py`
- [ ] `tests/test_api.py`
- [ ] `tests/test_parser.py`
- [ ] `tests/test_cli.py`

### CI
- [ ] `.github/workflows/ci.yml`
- [ ] Coverage badge in README
- [ ] Chaos tests gated to `main` branch only (too slow for PRs)
