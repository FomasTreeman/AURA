from fastapi import FastAPI, Response
from fastapi.responses import StreamingResponse
from prometheus_client import CollectorRegistry, Counter, generate_latest, CONTENT_TYPE_LATEST
import asyncio

app = FastAPI(title="AURA Phase 5 Service - Observability & UI shim")

REQUEST_COUNTER = Counter("phase5_requests_total", "Total requests to the phase5 service")


@app.get("/metrics")
def metrics():
    """Return Prometheus metrics in the default text format."""
    # Increment a simple counter to show dynamic metrics
    REQUEST_COUNTER.inc()
    output = generate_latest()
    return Response(content=output, media_type=CONTENT_TYPE_LATEST)


@app.get("/sse")
async def sse_stream():
    """A tiny Server-Sent Events stream for UI integration smoke tests."""

    async def event_generator():
        for i in range(5):
            yield f"data: phase5 event {i}\n\n"
            await asyncio.sleep(0.01)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/")
def root():
    return {"service": "phase5", "status": "ok"}
