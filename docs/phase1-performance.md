# Phase 1 – Performance Baseline

## Hardware

| Component | Spec |
|-----------|------|
| Platform  | macOS (Apple Silicon / x86) |
| Python    | 3.14.3 |
| Runtime   | CPU-only (no GPU) |

## Test Conditions

- Embedding model: `all-MiniLM-L6-v2` (SentenceTransformers, 384-dim, ~23 MB)
- LLM: `llama3.2:3b` via Ollama (4-bit quantized, ~2 GB)
- Vector DB: ChromaDB PersistentClient (cosine similarity, HNSW index)
- Chunk size: 1000 chars, overlap: 200 chars

## Ingestion Performance

| Document Size | Pages | Chunks | Ingest Time |
|--------------|-------|--------|-------------|
| Small (2 pg)  | 2     | 2      | ~1.2 s      |
| Large (25 pg) | 25    | 25     | ~4.8 s      |

**Breakdown:**
- PDF parse: ~0.05 s / page
- Presidio redaction: ~0.1-0.3 s / page
- Embedding (batch of 20): ~0.3-0.8 s
- ChromaDB insert: <0.1 s / batch

## Retrieval Performance

- Cold query (model not loaded): ~1.5-2.0 s (embedding model load)
- Warm query (model cached): ~30-80 ms
- ChromaDB cosine similarity search (top-5, 100 chunks): <5 ms

## End-to-End Query (with Ollama)

| Metric               | Value              |
|---------------------|--------------------|
| Time to first token  | ~1.5-3.0 s         |
| Full response (short)| ~4-7 s             |
| Full response (long) | ~6-12 s            |
| Target (spec)        | < 8 s on 16 GB RAM |

## Test Results

```
======================== 52 passed, 7 warnings in 11.14s ========================
```

- 33 unit tests (hashing, chunking, redaction)
- 19 integration tests (ingestion pipeline, retriever, edge cases)
- 0 failures

## Notes

- Python 3.14 is newer than the spec's recommended 3.12.3; all packages are compatible.
- Pydantic V1 compatibility warnings from LangChain are non-breaking.
- `DATE_TIME` and `NRP` entity types excluded from Presidio to avoid false positives on
  common business language ("quarterly", "year over year").
- The `en_core_web_sm` spaCy model is used; upgrading to `en_core_web_lg` would improve
  PERSON entity detection accuracy at the cost of ~560 MB additional disk space.
