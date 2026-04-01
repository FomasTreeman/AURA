**📜 Phase 6 Technical Specification: Completeness & Resilience**
*(Document Revocation, Model Manifest Gossip, Encrypted Backups, Chaos Testing)*

Phase 6 finalizes durability, consistency, and operational resilience.

Goal: Implement robust revocation & tombstoning, model-manifest gossip for answer determinism, encrypted backup/restore, and an automated chaos suite to validate resilience.

Success Criteria
- Revoked documents are never returned in subsequent queries after tombstone propagation.
- Model manifests are gossiped and enforced: nodes detect manifest mismatch and either refuse to synthesize or route to heavy-lifter.
- Encrypted backup and restore of ChromaDB and keystore succeed with CLI-tested round-trips.
- Chaos tests showing tolerable degradation and recovery for peer churn, CID corruption, and model manifest divergence.

Core Components
- `resilience/revocation.py` — tombstone publisher + local tombstone DB + tombstone TTL.
- `resilience/manifest_watcher.py` — signs and verifies model manifests, auto-alerting on mismatch.
- `resilience/backup.py` — encrypted backup (AES-256-GCM) with optional IPFS pin.
- `resilience/chaos.py` — orchestrates chaos tests for CI; scripts to simulate node restarts, corrupted vectors, and network partitions.

Backup & Restore Commands (example)
```bash
# backup
python -m aura.resilience.backup --out backup.enc --passphrase-file ./secret.txt

# restore
python -m aura.resilience.backup --restore backup.enc --passphrase-file ./secret.txt --target ./restored
```

Testing
- Backup round-trip test: backup -> wipe DB -> restore -> run Phase 1 acceptance tests.
- Manifest enforcement test: start mismatched model manifest -> queries get routed or blocked as policy dictates.
- Chaos suite: run `chaos.py` in CI nightly; assert recovery within acceptable SLA.

Acceptance Criteria
- All acceptance tests pass in CI, and recovery scripts documented in `docs/resilience/`.

Deliverables
- `backend/resilience/*`, backup CLI, manifest watcher, CI chaos pipeline (GitHub Actions or similar), and a recovery runbook `docs/resilience/runbook.md`.
