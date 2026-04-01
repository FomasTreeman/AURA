**📜 Phase 4 Technical Specification: Extreme Security & Data Integrity**
*(DIDs, ZKPs, Signed Model Manifests, IPFS CID Enforcement, Revocation)*

Phase 4 hardens the system with cryptographic identity, selective disclosure, and auditable integrity guarantees.

Goal: Implement DID-based identity, ZKP-based authorization tokens (or signed assertions), enforce IPFS CID integrity for documents, and implement revocation/tombstoning workflows.

Success Criteria
- Nodes hold DID keys and present verifiable credentials for query-level authorization.
- Peers accept queries only from authorized DIDs (certificate verification in the handshake).
- Documents are content-addressed (IPFS CID) and any mismatch between CID and stored vectors triggers rejection.
- Revocation path: when a local document is deleted, node publishes tombstone event; peers remove related vectors from future results.

Key Components
- `security/did.py` — DID creation, key rotation, export/import, and storage (local encrypted keystore).
- `security/zkp.py` — placeholder harness to integrate with Polygon ID or alternate ZKP provider; offers APIs: `create_auth_proof(claims)`, `verify_auth_proof(proof)`.
- `storage/ipfs_integration.py` — compute and validate CIDs (use go-ipfs or HTTP API), enforce pinning where applicable.
- `security/model_manifest.py` — signed manifest of model tag + quantization + hashing to ensure answer determinism.

Exact Commands & Tools
```bash
# install ipfs (macOS using Homebrew)
brew install ipfs
ipfs init
ipfs daemon &

# example: compute CID for file
ipfs add --cid-version=1 --raw-leaves -Q path/to/doc.pdf
```

Identity & Key Management
- Key type: use Ed25519 for signing, X25519 for ECDH key agreement.
- Keystore: encrypted local file using OS-level keyring (or password-protected via `cryptography` libs). Provide `aura key export` / `aura key rotate` CLI commands.

Proof & Authorization
- Queries must include either:
  - Signed envelope (Ed25519 sig over envelope), OR
  - ZKP auth proof token (if Polygon ID integration enabled).
- Revocation: implement signed revocation lists (signed by owner key) and distributed via Gossipsub topic `/aura/revocations/1.0.0`.

Testing
- Unit tests for DID key generation and signature verification.
- Integration: simulate a node with invalid CID in its vector DB — peers must reject its retrieval responses.
- Revocation test: publish tombstone, ensure peers exclude tombstoned vectors in subsequent queries.

Compliance & Privacy
- PII must never be shared in envelopes; only redacted chunks with provenance CID are allowed.
- Ensure local keystore cannot be exported without passphrase.

Deliverables
- `backend/security/*`, IPFS integration, CLI key management commands, test suite validating revocation and CID enforcement.
