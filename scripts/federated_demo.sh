#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# AURA Phase 3 – Federated RAG Demo
#
# Demonstrates: 2 nodes on different ports, each with separate documents,
# federated query returns merged results from both.
#
# Prerequisites:
#   - .venv activated:  source .venv/bin/activate
#   - Ollama running:   ollama serve (in a separate terminal)
#   - ollama pull llama3.2:3b (once)
#
# Usage:
#   chmod +x scripts/federated_demo.sh
#   scripts/federated_demo.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VENV="$PROJECT_ROOT/.venv/bin/python"

echo "=== AURA Phase 3 Federated RAG Demo ==="
echo ""

# ── Directory setup ──────────────────────────────────────────────────────────
NODE1_DATA="$PROJECT_ROOT/data/demo_node1"
NODE2_DATA="$PROJECT_ROOT/data/demo_node2"
mkdir -p "$NODE1_DATA/docs" "$NODE1_DATA/chroma" "$NODE1_DATA/identity"
mkdir -p "$NODE2_DATA/docs" "$NODE2_DATA/chroma" "$NODE2_DATA/identity"

# ── Create sample PDF documents ───────────────────────────────────────────────
echo "Creating sample documents…"

$VENV - << 'PYEOF'
import sys, fitz

# Node 1 document: Q3 Financial Report
doc1 = fitz.open()
page = doc1.new_page()
page.insert_text((72, 72),
    "Q3 2026 Financial Report\n\n"
    "Total revenue for Q3 was $4.2 million, a 12% increase year-over-year.\n"
    "Operating costs were $2.8 million, leaving operating income of $1.4 million.\n"
    "The primary revenue driver was the new enterprise SaaS product line."
)
doc1.save("/tmp/q3_report.pdf")
doc1.close()

# Node 2 document: Employee Handbook
doc2 = fitz.open()
page = doc2.new_page()
page.insert_text((72, 72),
    "Employee Handbook 2026\n\n"
    "All full-time employees receive 30 days of paid vacation per year.\n"
    "Health insurance covers dental and vision. Remote work is permitted 3 days/week.\n"
    "Performance reviews are conducted quarterly."
)
doc2.save("/tmp/employee_handbook.pdf")
doc2.close()

print("Documents created.")
PYEOF

cp /tmp/q3_report.pdf "$NODE1_DATA/docs/"
cp /tmp/employee_handbook.pdf "$NODE2_DATA/docs/"

# ── Start Node 1 (bootstrap) ──────────────────────────────────────────────────
echo ""
echo "Starting Node 1 (API :8001, P2P :9001)…"
OLLAMA_MODEL=llama3.2:3b \
CHROMA_PATH="$NODE1_DATA/chroma" \
INGEST_DIR="$NODE1_DATA/docs" \
P2P_PORT=9001 \
P2P_KEY_DIR="$NODE1_DATA/identity" \
P2P_MDNS_ENABLED=false \
P2P_BOOTSTRAP="" \
    $PROJECT_ROOT/.venv/bin/uvicorn backend.main:app \
    --port 8001 \
    --host localhost \
    --no-access-log &
NODE1_PID=$!
echo "Node 1 PID: $NODE1_PID"

sleep 3

# ── Get Node 1 peer_id ────────────────────────────────────────────────────────
echo "Getting Node 1 peer_id…"
NODE1_STATUS=$(curl -sf http://localhost:8001/network/status)
NODE1_PEER_ID=$(echo "$NODE1_STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin)['peer_id'])")
echo "Node 1 peer_id: $NODE1_PEER_ID"

# ── Ingest documents on Node 1 ────────────────────────────────────────────────
echo ""
echo "Ingesting documents on Node 1…"
curl -sf -X POST http://localhost:8001/ingest \
    -H "Content-Type: application/json" \
    -d "{}" | python3 -c "import sys,json; r=json.load(sys.stdin); print(f\"  Ingested {r['files_processed']} file(s), {r['total_chunks']} chunks\")"

# ── Start Node 2 (connects to Node 1) ────────────────────────────────────────
echo ""
echo "Starting Node 2 (API :8002, P2P :9002)…"
OLLAMA_MODEL=llama3.2:3b \
CHROMA_PATH="$NODE2_DATA/chroma" \
INGEST_DIR="$NODE2_DATA/docs" \
P2P_PORT=9002 \
P2P_KEY_DIR="$NODE2_DATA/identity" \
P2P_MDNS_ENABLED=false \
P2P_BOOTSTRAP="/ip4/localhost/tcp/9001/p2p/$NODE1_PEER_ID" \
    $PROJECT_ROOT/.venv/bin/uvicorn backend.main:app \
    --port 8002 \
    --host localhost \
    --no-access-log &
NODE2_PID=$!
echo "Node 2 PID: $NODE2_PID"

sleep 3

# ── Ingest documents on Node 2 ────────────────────────────────────────────────
echo "Ingesting documents on Node 2…"
curl -sf -X POST http://localhost:8002/ingest \
    -H "Content-Type: application/json" \
    -d "{}" | python3 -c "import sys,json; r=json.load(sys.stdin); print(f\"  Ingested {r['files_processed']} file(s), {r['total_chunks']} chunks\")"

sleep 2

# ── Check peer connectivity ────────────────────────────────────────────────────
echo ""
echo "Node 1 connected peers:"
curl -sf http://localhost:8001/network/peers | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"  {d['count']} peer(s): {[p['peer_id'][:16] for p in d['peers']]}\")"

echo "Node 2 connected peers:"
curl -sf http://localhost:8002/network/peers | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"  {d['count']} peer(s): {[p['peer_id'][:16] for p in d['peers']]}\")"

# ── Run federated query from Node 1 ──────────────────────────────────────────
echo ""
echo "=== Federated Query (no LLM) ==="
echo "Question: 'What is the Q3 revenue and how many vacation days do employees get?'"
echo ""
curl -sf -X POST http://localhost:8001/query/federated \
    -H "Content-Type: application/json" \
    -d '{"question": "What is the Q3 revenue and how many vacation days do employees get?", "top_k": 5}' \
| python3 - << 'PYEOF'
import sys, json
data = json.load(sys.stdin)
print(f"Query ID    : {data['query_id'][:16]}…")
print(f"Local chunks: {data['local_count']}")
print(f"Peer chunks : {data['peer_count']}")
print(f"Peers       : {data['peers_responded']}")
print(f"Duration    : {data['duration_ms']} ms")
print(f"\nTop {len(data['chunks'])} fused chunks:")
for i, c in enumerate(data['chunks'], 1):
    print(f"  [{i}] score={c.get('rrf_score',0):.4f} sources={c.get('rrf_sources',1)}")
    print(f"       source={c.get('source','?')} node={c.get('node_id','?')[:16]}")
    print(f"       text: {c.get('text','')[:80]}…")
PYEOF

echo ""
echo "=== Metrics ==="
curl -sf http://localhost:8001/metrics | grep "^aura_"

# ── Cleanup ───────────────────────────────────────────────────────────────────
echo ""
echo "Stopping nodes…"
kill $NODE1_PID $NODE2_PID 2>/dev/null || true
wait $NODE1_PID $NODE2_PID 2>/dev/null || true
echo "Demo complete."
