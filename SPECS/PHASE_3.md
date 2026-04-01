**📜 Phase 3 Technical Specification: Federated RAG Logic**
*(Parallel Retrieval, Reciprocal Rank Fusion, Synthesis, and Streaming)*

Phase 3 turns an Aura Node into a federated retriever: it merges local and peer results deterministically, ranks and fuses them, and drives the local LLM to synthesize grounded answers.

Goal: Implement deterministic, audited federated retrieval with fusion (RRF), source attribution, and streaming synthesis.

Success Criteria
- Node can issue a federated query that collects top-N results from local DB and authorized peers, performs RRF fusion, and returns an answer identical to a reference implementation within deterministic bounds.
- Responses include provenance (source CID, score, snippet) for every cited fact.

Core Components
- `rag/federated.py` — orchestrates query broadcast, collects responses, normalizes scores, runs RRF, and builds prompt context.
- `rag/rrf.py` — deterministic implementation of Reciprocal Rank Fusion (configurable `k=60` default).
- `rag/consensus.py` — policies for deduplication, censorship (tombstoned docs), and TTL handling.

Query Flow (detailed)
1. Receive user query locally.
2. Local retrieval: fetch top `L` chunks from ChromaDB with cosine similarity + metadata filters.
3. Create federated request envelope (see Phase 2 protocol) with ZKP indicating authorization (Phase 4 will expand ZKP specifics; Phase 3 uses signed assertion placeholder).
4. Publish to `/aura/query/1.0.0` with metadata: `query_id`, `query_hash`, `max_results`, `auth_sig`.
5. Peers perform local retrieval and reply directly (encrypted) to requester with `query_response` containing top `M` results and per-chunk score.
6. Requester collects responses until: (a) timeout, (b) quorum reached, or (c) max_responses.
7. Normalize scores to [0,1] using pre-agreed method (min-max per-query), then apply RRF:

   RRF_score = sum(1 / (k + rank_i)) for each ranking list

8. Select top-K fused passages and attach provenance. Build system prompt with explicit citations and return to LLM generator.

Prompt & Synthesis
- Use strict prompt template: system instruction, explicit context with numbered citations, citation policy (exact phrasing to include), user query. Insist on LLM only using provided context.
- Include `--sources:` block appended to end of answer with `[source CID] page X` lines.

Testing
- Unit tests for `rrf.py` with synthetic rankings (check deterministic outputs across seed variations).
- Integration test: 3-node federation where nodes have overlapping docs; verify fusion picks best unique passages and citations are correct.
- Determinism tests: run same query 10 times under identical inputs -> same fused ranking and same LLM prompt input.

Edge cases & rules
- Quorum policy: default `quorum = 2` peers + local results; configurable.
- Timeout policy: default 2s on LAN, 6s WAN; tunable via config.
- Duplicate content: dedupe by CID+chunk-hash; merge metadata arrays.

Performance
- Aim for retrieval + fusion in <200 ms on LAN for top-50 candidates.
- Cache per-query embeddings and intermediate fused list for short TTL (30s) to avoid spurious re-broadcasts.

Deliverables
- `backend/rag/federated.py`, `backend/rag/rrf.py`, tests, sample scripts `scripts/federated_demo.sh`, and documentation describing configuration knobs.
