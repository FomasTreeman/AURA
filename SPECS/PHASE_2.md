**📜 Phase 2 Technical Specification: P2P Mesh Network**
*(Peer Discovery, Gossipsub Pub/Sub, Encrypted Transport, NAT Traversal)*

This document is the developer-ready Phase 2 spec. It assumes Phase 1 (local sovereign node) is implemented and tested.

Goal: Integrate a robust P2P layer so Aura Nodes can discover peers, securely exchange encrypted retrieval requests/responses, and maintain an eventual-consistent peer graph with NAT traversal and minimal configuration.

Success Criteria (Phase 2 Complete)
- Local node can discover peers on LAN and internet (via rendezvous) using the same protocol.
- Implement Gossipsub topic `/aura/query/1.0.0` with authenticated, signed envelopes.
- Perform NAT traversal using libp2p's hole-punching; fallback to relay nodes when necessary.
- Demonstrate end-to-end encrypted request/response between two nodes in test harness.

Hardware & Software Baseline
- Same as Phase 1 with additional requirement: Docker and docker-compose for multi-node testing.
- Python 3.12.3 recommended.
- `py-libp2p` (pin to tested commit) and `aiodns` for mDNS fallback.

Exact Setup Commands
```bash
# create env
python -m venv .venv
source .venv/bin/activate
pip install py-libp2p==0.XX.X aiohttp cryptography python-dotenv
```

Core Components
- `network/peer.py` — peer identity management, keypair generation (Ed25519), DID-compatible key export.
- `network/libp2p_adapter.py` — thin wrapper exposing: start(), stop(), publish(topic, msg), subscribe(topic, handler), dial(peer_addr), get_peers().
- `network/protocol.py` — message shapes, signed envelope format, versioning, compression guidelines.

Protocol: Message Shape (JSON over encrypted stream)
- `envelope`: {
  "version": "1.0",
  "type": "query_request" | "query_response" | "peer_announce",
  "from": {"peer_id": "<libp2p-id>", "pubkey": "<ed25519-pem>"},
  "nonce": "<base64>",
  "body": <opaque, base64-encoded compressed protobuf>,
  "sig": "<base64-ed25519-signature>"
}

Notes:
- Body must always be encrypted with recipient public key (Curve25519 or hybrid ECDH+AES-GCM). For pub/sub broadcast (Gossipsub), use ephemeral symmetric encryption per topic and key distribution via signed envelopes.
- Never broadcast raw metadata that may leak PII.

API Endpoints (libp2p-adapter)
- `publish(topic:str, envelope:dict) -> None`
- `subscribe(topic:str, callback:Callable[[envelope], Awaitable[None]])`
- `dial(addr:str) -> PeerInfo`
- `get_peers() -> List[PeerInfo]`

File layout additions

```
backend/network/
├── __init__.py
├── peer.py
├── libp2p_adapter.py
├── protocol.py
└── rendezvous.py
```

Rendezvous & Bootstrap
- Provide two bootstrap options:
  - Local LAN discovery: mDNS + multicast DNS.
  - Public rendezvous: list of bootstrap multiaddrs (configurable).
- Include a small Docker-based relay (optional) for NAT-restricted networks.

Testing Plan
- Unit tests:
  - `peer.py` key generation + signature verification.
  - `protocol.py` envelope validation and versioning.
- Integration tests (docker-compose):
  - 3-node mesh: node A publishes a query_request; node B and C subscribe and respond; A receives encrypted responses and verifies signatures.
  - NAT simulation: use containers with iptables rules to emulate NAT; verify hole-punch fallback to relay.
- Security tests:
  - Envelope tamper detection: alter signature -> reject.
  - Replay protection: nonce TTL and duplicate detection.

Performance & Metrics
- Add `/metrics` counters for: peers_connected, messages_published_total, messages_received_total, failed_validations_total.

Acceptance Criteria
- Multi-node test passes in CI (via ephemeral Docker network).
- Relay fallback works in NAT simulation.
- All messages are signed and verified.

Pitfalls & Mitigations
- Py-libp2p maturity: vendor/freeze the tested commit. Keep adapter to allow future swap to Rust/Go implementations.
- mDNS noisy networks: provide opt-out and TTL tuning.

Deliverables
- `PHASE_2.md` (this file), `backend/network/*` implementation, docker-compose test harness, unit + integration tests, and documentation of bootstrap multiaddrs.
