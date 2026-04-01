# Phase 5 - Observability & UI shim

This small service is a minimal scaffold used for Phase 5 integration testing. It provides:

- `/` a health/status endpoint
- `/metrics` a Prometheus-compatible metrics endpoint
- `/sse` a tiny Server-Sent Events stream for frontend smoke tests

Quick start (local):

```bash
python -m pip install -r backend/phase5_service/requirements.txt
uvicorn backend.phase5_service.main:app --host 0.0.0.0 --port 8000
```

Run tests:

```bash
pytest -q
```
