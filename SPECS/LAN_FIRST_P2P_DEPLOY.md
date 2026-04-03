AURA/SPECS/LAN_FIRST_P2P_DEPLOY.md

# LAN‑First P2P Deployment & Multi‑Office Federation (AURA)

This spec describes a LAN‑first deployment model where every device in an office can act as a full AURA node (including hosting its own local model). The design assumes no mandatory cloud dependency for normal operation — nodes discover and federate across the office LAN. We also cover secure options for multi‑office federation (multiple LANs) while retaining the cloud deployment docs as an optional path for businesses with multi-site requirements.

Goals
- Allow each office device to run as a self‑contained node (RAG + local LLM host).
- Keep data within office LAN by default.
- Provide secure, auditable, and scalable ways to federate across multiple offices when needed.
- Maintain strong security, update, and monitoring practices for air‑gapped / on‑prem environments.

Assumptions
- Each node runs:
  - AURA backend (FastAPI) container/service.
  - Local LLM host (Ollama or equivalent) on the same device or a dedicated machine in the same LAN.
  - Local vector DB instance (Chroma) or a small shared office Chroma instance accessible from nodes.
  - Redis for coordination (optional — local per device or a single HA Redis in LAN).
- LAN is trusted within an office; cross‑office traffic is not trusted unless explicitly configured (VPN/mTLS).
- Devices have connectivity to at least a central office registry or peer discovery mechanism for multi‑office federation.

1) Single‑Office (LAN) Deployment Patterns

1.1 Per‑Device Full Node (recommended for strong privacy)
- Each device runs its own AURA stack + model. Benefits:
  - Data never leaves the device unless explicitly shared.
  - Low inter‑device latency for local queries.
  - Resilience: device can answer queries offline.
- Requirements per device:
  - CPU/RAM tuned to model size. Example guidance:
    - Small CPU models: 4–8 vCPU, 8–16 GB RAM.
    - Medium / heavier: 8+ vCPU, 32+ GB RAM, GPU preferred.
  - Disk: local SSD for Chroma DB and model artifacts.

1.2 Shared Office Model Host
- If devices are constrained, run a single Ollama host in the office (on a server); other devices use it via private LAN.
- Pros: centralized model management and lower per‑device resource need.
- Cons: central point of failure and potential privacy tradeoffs (all queries run through central host).

1.3 Discovery & Connectivity (LAN)
- mDNS (zeroconf) is used by default for zero‑config discovery across devices on the same LAN.
- Important env/config knobs:
  - `P2P_MDNS_ENABLED=true` (default)
  - `P2P_HOST=0.0.0.0` (listen on all interfaces)
  - `P2P_ADVERTISE_HOST=<device-lan-ip-or-hostname>` (advertised IP for other LAN nodes to dial)
- Docker & mDNS caveat:
  - If running nodes in containers, use either:
    - Host networking (`--network host`) so mDNS and ports are bound to the host NIC; or
    - Bridge networking with explicit port mapping and a local rendezvous server (see below).
- Example minimal env (for documentation / ops):
```/dev/null/.env#L1-10
P2P_MDNS_ENABLED=true
P2P_HOST=0.0.0.0
P2P_PORT=9000
P2P_ADVERTISE_HOST=192.168.1.42   # device LAN IP
RENDEZVOUS_URL=                   # leave empty for pure LAN mDNS
```

2) Onboarding & Provisioning
- Device provisioning steps (recommended):
  1. Install container runtime or system package.
  2. Install/update local model artifacts or point to office model host.
  3. Generate device identity keys (done by `PeerIdentity.load_or_create()`).
  4. Set `P2P_ADVERTISE_HOST` to the device's LAN IP (or a stable hostname).
  5. Start the AURA service (systemd or docker-compose).
- For fleet provisioning:
  - Use signed images + signed configuration bundles.
  - Automate key injection with secure USB onboarding or an internal MDM/Provisioning server.

3) In‑LAN Hardening & Best Practices
- Firewall: only allow P2P ports among trusted LAN segment. Block P2P from general guest network.
- Network segmentation: place AURA devices on a private VLAN.
- Authentication: always enable and enforce peer identity checks. Use the built-in signing and add mTLS for P2P if possible.
- Logging: redact query content from central logs; store sensitive logs locally or in a locked office log store.

4) Multi‑Office Federation (two or more LANs)

4.1 Threat model & design choices
- Cross‑office connections traverse untrusted networks (internet). You must:
  - Authenticate and authorize peers.
  - Encrypt traffic (end‑to‑end).
  - Limit exposure (only open necessary ports over secured tunnels).
- Two main secure bridging patterns:
  - Site‑to‑site VPN (preferred).
  - Rendezvous + authenticated, encrypted direct connections (peer dial) over public IPs with strict controls.
- Alternative: use a cloud relay/rendezvous only for brokered discovery, but enforce E2E encryption for payloads.

4.2 Option A — Site‑to‑site VPN (recommended)
- Setup:
  - Each office network connects to the others via a robust VPN (WireGuard, IPsec).
  - AURA nodes use local LAN IPs; VPN ensures routability.
  - mDNS can still be used inside each LAN; Rendezvous optional for cross‑site discovery.
- Pros:
  - Simpler trust: the network itself is trusted.
  - No need to expose P2P ports to public internet.
- Cons:
  - Requires network admin effort.

4.3 Option B — Secure Rendezvous + Direct Dial
- Components:
  - Per‑office Rendezvous server (or a centrally managed rendezvous server you control).
  - Nodes register their advertised, reachable multiaddrs (public IP + port) at the rendezvous.
  - Nodes attempt direct TLS‑protected dials to discovered peers.
- Security controls:
  - Use PKI: node certificates signed by central CA per organization.
  - Use ephemeral tokens or signed auth blobs (signature included in proto).
  - Enforce strict handshake verification (existing code includes signing; extend to require CA validation).
- If NAT prevents direct connections: use a relay/ TURN‑like service inside your infrastructure (self‑hosted relay) with authenticated connections.

4.4 Option C — Cloud Relay (hybrid, optional)
- Keep data local for normal operations; cloud used only as a discovery/relay plane.
- Use E2E encryption so relay cannot read payloads.
- Useful when offices cannot maintain VPNs or for managed multi‑office features.

5) Data & Backup Strategy (LAN‑First)
- Each device backups:
  - Local Chroma DB snapshots to local NAS or encrypted USB.
  - Regular incremental snapshots (automated cron/backup job).
- Optional central backup:
  - Securely push encrypted snapshots to a central office backup server (over VPN) or to an S3 bucket accessible only from office gateway.
  - Use per‑device encryption keys and rotate regularly.

6) Updates & CI/CD for Air‑Gapped / LAN‑First Environments
- Use signed artifacts:
  - Build images in CI (central), sign them with sigstore/cosign.
  - Office nodes pull signed images from an internal registry (air‑gapped mirror) or receive images via secure USB/manual staging.
- Update strategy:
  - Staged rollout: pilot 1–2 devices → office → multi‑office.
  - Rollback image tags available locally.
- For multi‑office without internet:
  - Maintain internal artifact registry in each office (Harbor, Artifactory) and sync via secure channels.

7) Monitoring & Ops (LAN)
- Per‑device metrics export via Prometheus node_exporter + AURA Prometheus metrics.
- Central office aggregator:
  - A Prometheus pull server in office collects metrics from devices.
  - Alerting for resource issues, high token generation rates, model errors.
- For multi‑office:
  - Aggregate only metadata (counters/health) at HQ, avoid sending raw queries.

8) Security Controls & Key Management
- Identity keys:
  - Generate locally; optionally enroll via PKI for organization.
  - Provide central revocation list (Revocation Manager) that nodes fetch from HQ over secure channel.
- Certificate management:
  - Use internal CA. Use short‑lived certificates for devices.
- Access control:
  - API keys for users; SSE endpoints require auth.
  - Enforce per‑device quotas and rate limits.
- Audit:
  - Record ingestion, deletions, and administrative actions; keep audit logs locally and push metadata to central audit server if permitted.

9) Failure Modes & Offline Operation
- Nodes should handle offline peers gracefully:
  - Timeouts and local fallback (local retrieval only).
  - Queue outbound rendezvous registrations for eventual delivery.
- Reconciliation:
  - Federated fusion is resilient to missing peers; results degrade to local-only.

10) Operational Playbook (concise)
- New office onboarding:
  1. Provision gateway (VPN endpoint or Rendezvous server).
  2. Install internal registry & backups.
  3. Provision a small number of pilot nodes; verify discovery and federation.
  4. Rollout to devices.
- Incident response:
  - If a device is compromised: revoke its keys, remove it from rendezvous, rotate office keys, and audit ingestion logs.
- Periodic tasks:
  - Rotate keys quarterly, run dependency security scans weekly, run backup verification monthly.

11) Recommended Config & Env Vars (ops cheat sheet)
- `P2P_MDNS_ENABLED=true`
- `P2P_HOST=0.0.0.0`
- `P2P_PORT=9000`
- `P2P_ADVERTISE_HOST=<device-lan-ip-or-hostname>`
- `RENDEZVOUS_URL=http://<office-rendezvous-host>:<port>` (optional)
- `OLLAMA_BASE_URL=http://localhost:11434` (or office model host)
- `CHROMA_PATH=/var/lib/aura/chroma`

12) Tests & Validation
- Unit/integration:
  - Local dial test (node A dials node B on loopback).
  - mDNS discovery test across two VMs on same LAN.
- Multi‑office:
  - VPN test: bring up two VMs across a site-to-site VPN and confirm discovery & federation.
  - Rendezvous test: register and discover peers via office rendezvous.
- Security:
  - Validate that nodes reject peers without valid signatures.
  - Simulate revoked keys and ensure calls are denied.

13) When you might still use cloud infra
- Centralized admin, backups, or cross‑office analytics where allowed by policy.
- A secure, central Rendezvous server or relay to ease connectivity, but with strict E2E encryption so content remains private.
- Use cloud only for orchestration and monitoring aggregation if business policy allows; keep query payloads and data on‑prem.

14) Deliverables & Next Steps I can produce
- `docker-compose.dev.yml` examples for host‑network and bridge network modes.
- Sample `rendezvous` server instructions and a minimal deploy script for an office.
- Example scripts to provision device keys and enroll with a central CA.
- A test harness describing how to simulate multi‑office federation in your lab.

---

This LAN‑First approach prioritizes data residency and privacy while keeping the system flexible enough to federate across offices securely. If you want, I’ll produce any of the deliverables listed in section 14 (compose, rendezvous server, provisioning scripts, or a lab test plan).