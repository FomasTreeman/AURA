**📜 Phase 1 Technical Specification: Sovereign Local Node**  
*(Detailed Development Blueprint – Fully Offline RAG – No Ambiguity)*

This document is the **complete, exhaustive, ready-to-code specification for Phase 1 only**.  
You will build a **100 % functional, offline RAG system** that can ingest documents, redact PII, store vectors locally, and answer questions using a local LLM — **without any networking, peers, or external services**.

**Goal of Phase 1**: Prove the core “sovereign node” foundation. When this phase is complete, you have a production-grade local RAG that can be used immediately and serves as the base for all future phases.

---

### 1. Phase 1 Objectives (What Must Be Delivered)
By the end of Phase 1 you must have:

- A single Python application (`aura-node`) that runs entirely offline.
- Full document ingestion pipeline: PDF → PII redaction → chunking → embedding → persistent local vector store.
- A local quantized LLM that answers questions **only** using the ingested documents (no hallucinations from general knowledge).
- A FastAPI backend exposing two REST endpoints:
  - `POST /ingest` (or CLI equivalent)
  - `POST /query` (returns streamed response)
- A simple terminal CLI for quick testing.
- Complete observability, logging, and testing suite.
- All data and models stored on local disk only.

**Success Criteria (Milestone – “Phase 1 Complete”)**  
You can run the node, drop 5–10 real PDFs into a folder, ingest them, then ask domain-specific questions and receive accurate, grounded answers **with zero internet access**. The system must handle 500+ page PDFs and return answers in < 8 seconds on 16 GB RAM hardware.

---

### 2. Prerequisites & Environment Setup (Exact Commands – No Room for Error)

**Hardware Baseline**  
- CPU: 8-core minimum  
- RAM: 16 GB minimum (24 GB+ recommended)  
- Disk: 20 GB free (for models + vector DB)  
- GPU: Optional (CPU-only works perfectly for this phase)

**Software Requirements**  
- Python 3.11 or 3.12 (use 3.12.3 for best performance)  
- Ollama installed and running (`ollama serve` in background)  
- Git, Docker (for later phases, but install now)

**Exact Setup Commands** (run in order):

```bash
# 1. Create project root
mkdir -p aura/backend && cd aura

# 2. Virtual environment
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate

# 3. Install exact dependencies (Phase 1 only)
pip install \
    fastapi uvicorn \
    chromadb \
    presidio-analyzer presidio-anonymizer \
    pymupdf sentence-transformers \
    langchain langchain-community langchain-chroma \
    python-dotenv rich typer \
    httpx  # for future testing

# 4. Pull the exact model we will use
ollama pull llama3.2:3b     # 3B quantized – fast and fits comfortably in 16 GB
# Alternative for slightly better quality: ollama pull llama3.2:8b (requires 24+ GB)
```

Create `.env` in project root:
```env
OLLAMA_MODEL=llama3.2:3b
CHROMA_PATH=./data/chroma_db
INGEST_DIR=./data/documents
MAX_CHUNK_SIZE=1000
CHUNK_OVERLAP=200
EMBEDDING_MODEL=all-MiniLM-L6-v2
```

---

### 3. Detailed Components & Implementation (Exact Requirements)

#### A. Document Ingestion Pipeline (Mandatory Order)
1. **PDF Parsing** – Use `pymupdf` (fastest and most reliable for structured PDFs).
2. **PII Redaction** – Microsoft Presidio must run **before** any chunking/embedding.
   - Analyzer: `PresidioAnalyzer()` with default recognizers + `PERSON`, `PHONE_NUMBER`, `EMAIL_ADDRESS`, `US_SSN`, `CREDIT_CARD`.
   - Anonymizer: Replace with `<REDACTED>` or synthetic placeholders.
3. **Chunking** – RecursiveCharacterTextSplitter from LangChain (`chunk_size=1000`, `chunk_overlap=200`).
4. **Embedding** – `SentenceTransformer` with model `all-MiniLM-L6-v2` (local, fast, 384-dim).
5. **Storage** – ChromaDB in **persistent** mode (`persist_directory=CHROMA_PATH`).
   - Collection name: `aura_documents`
   - Metadata stored per chunk: `{"source": filename, "page": int, "cid": sha256_hash_of_original_doc}`

#### B. RAG Query Pipeline
- Retrieve top-5 chunks using ChromaDB similarity search (`similarity_search_with_score`, threshold 0.3).
- Build prompt template (system + context + user query).
- Call Ollama via `langchain_community.llms.Ollama` with `streaming=True`.
- Return streamed tokens via FastAPI `StreamingResponse`.

#### C. Backend API (FastAPI)
- Run with `uvicorn backend.main:app --reload --port 8000`
- Endpoints:
  - `POST /ingest` – Accepts `{"directory": str}` or multipart files.
  - `POST /query` – Accepts `{"question": str}` and returns streamed JSON lines.

#### D. CLI Interface (for quick testing)
Use `typer` CLI:
```bash
python -m aura.cli ingest --dir ./data/documents
python -m aura.cli query "What is our Q3 revenue target?"
```

---

### 4. Exact Code Structure (Create These Files Exactly)

```
backend/
├── __init__.py
├── main.py                 # FastAPI app
├── config.py               # loads .env + constants
├── ingestion/
│   ├── pipeline.py         # Presidio → chunk → embed → Chroma
│   ├── redactor.py         # Presidio wrapper
│   └── parser.py           # PyMuPDF wrapper
├── rag/
│   ├── retriever.py        # ChromaDB query
│   ├── generator.py        # Ollama streaming
│   └── prompt.py           # system prompt template
├── database/
│   └── chroma.py           # ChromaDB client singleton
├── cli.py                  # Typer CLI
└── utils/
    ├── hashing.py          # SHA-256 for document CID
    └── logging.py          # structured logging
```

**Key File Requirements**:
- Every function must have type hints and docstrings.
- All paths must be relative to project root and respect `.env`.
- Error handling: graceful failures with clear Rich console output.

---

### 5. Testing Plan (Must Be Performed Before Declaring Phase 1 Complete)

**A. Unit Tests** (`tests/unit/`)
- Test Presidio redaction on sample PII text.
- Test chunking preserves overlap correctly.
- Test SHA-256 hashing is deterministic.

**B. Integration Tests** (`tests/integration/`)
- Ingest 3 test PDFs (one with PII, one large, one multi-page).
- Verify ChromaDB collection contains correct count and metadata.
- End-to-end query test: ask a question that can only be answered from the ingested docs.

**C. Manual / Acceptance Tests**
1. Start node: `uvicorn backend.main:app --port 8000`
2. Ingest folder containing real enterprise PDFs (contracts, reports, etc.).
3. Run 10 varied questions:
   - Direct fact extraction
   - Multi-document synthesis
   - Question that should return “I don’t know” (no relevant chunks)
4. Verify:
   - All PII is redacted in stored chunks
   - Answers are grounded (include source citations)
   - Response time < 8 seconds
   - No internet connection during entire test

**D. Performance Baseline**
- Measure cold-start query time and warm-cache time.
- Record in `docs/phase1-performance.md`

**E. Chaos / Edge Cases**
- Ingest corrupted PDF → must fail gracefully.
- Query with empty DB → must return clear “no documents” message.
- Redact extreme PII volume → must not crash.

---

### 6. Common Pitfalls & Mandatory Mitigations
- **Ollama not running** → Add startup check in `main.py` that raises clear error.
- **ChromaDB lock issues** → Always use `chromadb.PersistentClient` and close properly.
- **Embedding model mismatch** → Hard-code the exact model name everywhere.
- **Memory explosion on large PDFs** → Chunk and embed in batches of 20 pages max.
- **Presidio false negatives** → Add custom recognizer for company-specific PII if needed.
- **Streaming not working** → Use `langchain`’s built-in `astream` and FastAPI `StreamingResponse` correctly.

---

### 7. Deliverables at End of Phase 1
- Working `backend/` folder with all files above.
- `tests/` folder with ≥ 15 passing tests.
- `docs/phase1-completion.md` containing:
  - Screenshot of CLI query
  - Screenshot of FastAPI Swagger UI
  - Performance numbers
  - List of ingested documents used in final test
- Updated `README.md` section marked “✅ Phase 1 Complete”
- Git commit: “Phase 1 – Sovereign Local Node complete – offline RAG working”

---

**You now have zero ambiguity.**  
Start coding **today** using the exact structure, commands, and testing plan above. Phase 1 is deliberately self-contained so you get a working, impressive system quickly before moving to the distributed complexity of Phase 2.

When Phase 1 is complete and all tests pass, reply with **“Phase 1 done”** and I will immediately give you the **equally detailed Phase 2 spec** (P2P Mesh Network with libp2p Gossipsub).

You’re ready. Let’s build the foundation perfectly. 🚀

Any questions before you start coding?