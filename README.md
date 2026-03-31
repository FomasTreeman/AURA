# 🌐 Project AURA – Advanced Universal Retrieval Architecture (Decentralized Edition)

**A sovereign, local-first, peer-to-peer Federated RAG platform.**  
Your company’s knowledge lives on employee laptops — not in the cloud. Zero data leaves the trusted mesh.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-ready-blue)](https://docker.com)
[![Stars](https://img.shields.io/github/stars/yourusername/aura)](https://github.com/yourusername/aura)

---

### ✨ What is AURA?

AURA turns every workstation into an **Aura Node** — a fully independent, secure knowledge shard in a decentralized P2P mesh.

- Documents stay 100 % on-device (ingested → redacted → vectorized locally).
- Queries are broadcast securely via libp2p Gossipsub.
- Authorized peers return encrypted snippets; your local LLM (Ollama + vLLM) synthesizes the answer.
- Raw data **never** touches the public internet or a central server.

Built as a **portfolio-grade side project** to master:
- Distributed systems & P2P networking
- Applied cryptography (DIDs + ZKPs)
- Edge AI / quantized inference
- GreenOps & sustainable infrastructure
- High-performance local RAG

---

### 🚀 Key Features

- **True local-first sovereignty** – No cloud, no S3, no central vector DB
- **Zero-trust security** – Polygon ID DIDs + Zero-Knowledge Proofs for authorization
- **Tamper-proof integrity** – IPFS Kubo CIDs + SHA-256 on every document
- **PII protection** – Microsoft Presidio redaction pipeline (runs before vectorization)
- **Federated RAG with Reciprocal Rank Fusion (RRF)**
- **Carbon-aware scheduling** – Delays background indexing during high-carbon grid periods
- **Real-time streaming UI** – Next.js 15 + Server-Sent Events
- **Observable & measurable** – Prometheus metrics + SCI (Software Carbon Intensity) dashboard
- **Document revocation** – Live deletion/update propagation across the mesh
- **Model consistency** – Pinned LLM manifest shared via gossip
- **One-command multi-node demo** – `docker compose up`

---

### 🏗️ Architecture Overview

```mermaid
graph TD
    A[User Query] --> B[Local Aura Node]
    B --> C[Local ChromaDB]
    B --> D[libp2p Gossipsub Broadcast + ZKP Credential]
    D --> E[Peer Nodes]
    E --> F[Local Vector Search + Presidio-protected Snippets]
    F --> B
    B --> G[RRF Fusion]
    G --> H[Ollama / vLLM Inference]
    H --> I[Next.js UI + SSE Streaming]
