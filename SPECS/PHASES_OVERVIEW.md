**📚 AURA Phases Overview (Roadmap & Dependencies)**

This document maps the final, developer-ready phase breakdown derived from the master `SPEC.md`. Each phase below is a standalone deliverable with clear objectives, acceptance criteria, tests, and exact commands where applicable. Implement phases in order; downstream phases depend on upstream artifacts.

Phases (order-sensitive):
- Phase 1: Sovereign Local Node — fully offline RAG (already authored in `PHASE_1.md`).
- Phase 2: P2P Mesh Network — libp2p/Gossipsub integration, peer discovery, NAT traversal.
- Phase 3: Federated RAG Logic — parallel retrieval, Reciprocal Rank Fusion (RRF), synthesis.
- Phase 4: Extreme Security & Integrity — DIDs, ZKPs, IPFS CID enforcement, signed manifests.
- Phase 5: UI, Observability & GreenOps — Next.js streaming UI, Prometheus/Grafana, carbon-aware scheduling.
- Phase 6: Completeness & Resilience — revocation, model manifest gossip, encrypted backups, chaos testing.

Implementation guidance:
- Implement exactly in order. Each phase must produce a testable artifact and automated tests (unit + integration).
- Use Docker for reproducible local testing. Each phase must include a minimal `docker-compose.yml` snippet when networking is required.
- Keep all tooling pinned (Python versions, model tags, library versions) and record exact commands used to validate.

Delivery checklist for each phase:
- Objectives: short checklist.
- Environment & exact setup commands.
- Component list and file layout.
- API and protocol definitions (endpoints, message shape, ports).
- Testing: unit, integration, performance, chaos.
- Acceptance criteria & success metrics.
- Known pitfalls and mitigations.

Use the corresponding `PHASE_X.md` files for detailed, actionable specs.
