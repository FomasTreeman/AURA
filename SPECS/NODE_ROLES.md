# Node Roles & Role-Based Architecture — AURA

Purpose
- Explain why you might split AURA into different node types rather than running every node as a full all-in-one instance.
- Provide recommended node roles, mapping to hardware and topology (LAN-first and multi-office), pros/cons for each role, security and operational considerations, and a suggested migration path from a single-node setup to a role-separated deployment.
- Help you decide whether role separation is worthwhile for your business use case.

Summary (short)
- You don't need multiple node types to get started — a single "full" node per device is simplest and preserves privacy/locality.
- As you scale (many devices, heavier models, multi-office federation), splitting responsibilities across specialized node types yields better resource utilization, reliability, security, and operational control.
- Aim to start simple and introduce roles incrementally where there is measurable benefit.

Core node roles (definitions)
1. Full Node (All-in-one)
   - Runs: AURA backend, Ollama (model), Chroma DB, Redis (optional), and P2P adapter.
   - Use when: single-device deployments or per-device privacy is required.
   - Pros: simple, local-first, data stays local.
   - Cons: high per-device resource needs; updating models/images across fleet is heavier.

2. Model Node (Inference / Model Host)
   - Runs: Ollama (or other LLM host) only; exposes model API.
   - Use when: devices are resource constrained or you want centralised model management in an office.
   - Pros: easy scaling of model resources, central model updates, better GPU utilization.
   - Cons: single point of model failure (mitigate with HA/pools); may affect privacy if queries cross devices.

3. Retrieval / Vector Node
   - Runs: Chroma (vector DB), embedding cache, possibly embedding service.
   - Use when: dataset is large and you want shared index among multiple frontends.
   - Pros: centralized index, efficient memory/disk usage, easier to back up and govern.
   - Cons: introduces network hop and potential sensitivity of cross-device retrieval.

4. Query / API Node (Frontend)
   - Runs: FastAPI endpoints, SSE, auth layer, rate limiting, light orchestration calling retrieval/model nodes.
   - Use when: separate API surface is needed for load balancing, auth, or explicit per-user quotas.
   - Pros: stateless horizontal scaling, clear boundary for authentication/observability.
   - Cons: additional network hops add latency.

5. Ingest / Indexer Node
   - Runs: ingestion pipeline, chunking, embedding, and writing to Chroma.
   - Use when: ingestion is heavy or controlled (admin-only), or for scheduled re-indexing jobs.
   - Pros: separates heavy CPU/IO ingestion from query path.
   - Cons: more components to operate.

6. Coordinator / Orchestrator Node
   - Runs: federation coordinator, rendezvous server, node registry, revocation manager, and admin UI endpoints.
   - Use when: you need central trust, bootstrapping, and management across many devices or offices.
   - Pros: central policy enforcement and discovery.
   - Cons: becomes a management plane and must be highly available.

7. Edge / Gateway Node
   - Runs: Tailscale/ WireGuard gateway, subnet router, optional model or index caches.
   - Use when: you want a single per-office egress point for inter-office federation or to represent office LAN to the tailnet.
   - Pros: simplified cross-office networking and controlled exposure.
   - Cons: gateway is a critical component; secure and monitor it.

8. Cache / Redis Node
   - Runs: Redis for sessions, rate-limiting tokens, and small caches.
   - Use when: you want shared session state, rate limiting, or job queues across multiple API/query nodes.
   - Pros: consistent session/rate-limiting and low-latency caching.
   - Cons: must be highly available and secured on LAN/VPN.

9. Monitoring / Logging Node
   - Runs: Prometheus, Grafana, and log collectors (Fluentd/Vector).
   - Use when: you need aggregated telemetry and alerts.
   - Pros: observability at fleet-level.
   - Cons: telemetry may reveal metadata — redact sensitive content.

When to split roles (practical signals)
- CPU/GPU constraints: you can't run full model and DB on every device affordably.
- Cost efficiency: a few model nodes with GPUs share load more cheaply than multiple under-provisioned local nodes with small CPU models.
- Management & compliance: central index and central policy enforcement simplifies audits and backups.
- Performance: retrieval and inference latency improves when you colocate heavy components on better hardware.
- Multi-office federation: coordinator/rendezvous becomes useful for discovery and governance.

Topologies & examples
1. Single-office, privacy-first (small team)
   - Per-device Full Node. mDNS discovery. No cloud components.
   - Good when every device must keep its data local and models on-device.

2. Office with shared model host (small-mid team)
   - Per-device Query/API Node + one or more Model Nodes (Ollama) in office.
   - Chroma can be local per-device or a single Retrieval Node.
   - Use host networking or tailscale to connect.

3. Multi-office, hybrid (enterprise)
   - Each office: Edge Gateway + a pool of Model Nodes + Retrieval Node.
   - Central Coordinator (cloud or HQ) for bootstrapping, policy, audit logs.
   - Tailscale or site-to-site VPN connects offices.

Microservices considerations (is this microservices?)
- Yes — role separation is effectively a microservices architecture:
  - Clear separation of concerns, bounded contexts, independent scaling.
  - You gain deployment flexibility (scale model pool, scale API pods separately).
  - You pay complexity cost (network, observability, testing, deployment pipelines).
- For a small, privacy-first RAG app, that complexity may not justify the benefits initially.
- Recommendation: start monolith/all-in-one for dev and small deployments; introduce microservice splits when metrics or operational constraints demand it.

Security & confidentiality trade-offs
- Per-device full nodes maximize data residency; fewer attack surfaces for cross-device exfiltration.
- Centralized model or retrieval nodes expose a single point that, if compromised, could leak aggregated data; mitigate with:
  - Strong transport encryption (Tailscale/WireGuard), application-level signing, and per-node identity revocation.
  - Role-based access control (RBAC) and network ACLs limiting who can query which node.
- Coordinator/rendezvous servers must be hardened (auth, ACLs, audit logs).

Operational implications (deploy/upgrade/monitor)
- Upgrade strategy:
  - With specialized roles you can upgrade model nodes first, test, then point API nodes to new hosts — less risky than full-fleet upgrades.
- CI/CD:
  - Independently build & test images for each role. Use canary or blue/green for model nodes (especially GPU-backed).
- Observability:
  - Correlate traces across components: request ID, query ID, and peer IDs must propagate.
- Failure isolation:
  - Role separation confines failures (e.g., model node crash affects only inference, not ingestion).
- Cost & resource mapping:
  - Model Nodes: GPUs, high RAM.
  - Retrieval Nodes: RAM + fast SSD (Chroma).
  - API Nodes: CPU, moderate RAM.
  - Indexer: CPU-heavy, burst-oriented.

Developer experience and testing considerations
- Keep test harnesses for each role (mock/stub remote services).
- Provide a `docker-compose.*` recipe for integrated development:
  - `docker-compose.full.yml` (all-in-one)
  - `docker-compose.split.yml` (api + model + chroma + redis)
- Include end-to-end tests that exercise federated queries across roles.

Recommended incremental migration path
1. Start: Full Node per device (developer/early-stage).
2. Next: Move ingestion to a dedicated Indexer Node (if ingestion becomes CPU heavy).
3. Next: Host a Model Node per-office if you need heavier models or GPUs.
4. Next: Extract Retrieval Node if you want a shared index per-office.
5. Next: Add Coordinator/Rendezvous for multi-office control and governance.
6. Throughout: move auth, rate limiting, and SSE security to API nodes.

When role separation is a waste of time
- If you are a small team (<= 5 nodes) with light models and a strong requirement that every device keep data local, role separation often adds complexity without enough benefit.
- If your primary goal is privacy and simplicity, keep to full nodes and invest in automation for image updates and local backups instead.

Concrete recommendations for AURA (practical)
- Default: keep codebase and config able to run as a Full Node with a single `docker-compose` flow for local dev.
- Provide optional compose/helm values to split roles (Model Node + API Node + Chroma + Redis).
- Provide a sample role-split topology in `SPECS/` (you can adapt what we already have: `SPECS/DEVOPS_AUTODEPLOY.md`, `SPECS/LAN_FIRST_P2P_DEPLOY.md`, `SPECS/TAILSCALE_INTEGRATION.md`).
- Instrument request/query IDs so you can trace across nodes.
- Implement role-aware health checks and graceful degradation (API returns local-only fallback if the model node is unreachable).
- Enforce auth & quotas at the API Node boundary, not in model nodes.

Closing (how I would proceed)
- I recommend you start simple: run full nodes on devices and measure where constraints appear (CPU, RAM, update frequency, cross-office needs).
- When you see real constraints, split the most painful responsibility first (model hosting), then iterate to retrieval/index separation.
- I can help you produce `docker-compose.split.yml` and CI job templates for role-based builds and tests, or a small design doc mapping roles to instance types (VM/GPU/edge).

If you'd like, tell me whether you prefer "privacy-first (per-device full node)" or "centralized model per office" and I will produce a concrete deploy & CI plan for that topology.