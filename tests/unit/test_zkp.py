"""
Unit tests for backend.security.zkp.
Covers: proof creation, verification, scope enforcement, replay protection, tamper detection.
"""
import base64
import time

import pytest

from backend.network.peer import PeerIdentity
from backend.security.zkp import (
    AuthClaims,
    AuthProof,
    SCOPE_ADMIN,
    SCOPE_QUERY,
    create_auth_proof,
    verify_auth_proof,
)


@pytest.fixture
def identity():
    return PeerIdentity.ephemeral()


class TestAuthProofCreation:
    """Tests for create_auth_proof()."""

    def test_creates_proof_with_correct_peer_id(self, identity):
        """Proof must carry the correct peer_id."""
        proof = create_auth_proof(identity)
        assert proof.claims.peer_id == identity.peer_id

    def test_proof_type_is_ed25519_assertion(self, identity):
        """Default proof type must be 'ed25519_assertion'."""
        proof = create_auth_proof(identity)
        assert proof.proof_type == "ed25519_assertion"

    def test_proof_has_non_empty_signature(self, identity):
        """Proof must carry a non-empty base64 signature."""
        proof = create_auth_proof(identity)
        assert len(proof.signature_b64) > 0
        base64.b64decode(proof.signature_b64)  # must not raise

    def test_proof_has_random_nonce(self, identity):
        """Two proofs must have different nonces."""
        p1 = create_auth_proof(identity)
        p2 = create_auth_proof(identity)
        assert p1.claims.nonce != p2.claims.nonce

    def test_proof_includes_pubkey(self, identity):
        """Claims must include ed25519_pubkey_b64 for verification."""
        proof = create_auth_proof(identity)
        assert proof.claims.ed25519_pubkey_b64 == identity.ed25519_pubkey_b64

    def test_default_scope_is_query(self, identity):
        """Default scope must be SCOPE_QUERY."""
        proof = create_auth_proof(identity)
        assert proof.claims.scope == SCOPE_QUERY

    def test_admin_scope(self, identity):
        """Admin scope can be set explicitly."""
        proof = create_auth_proof(identity, scope=SCOPE_ADMIN)
        assert proof.claims.scope == SCOPE_ADMIN

    def test_serialise_roundtrip(self, identity):
        """AuthProof.to_dict() / from_dict() must be lossless."""
        proof = create_auth_proof(identity)
        restored = AuthProof.from_dict(proof.to_dict())
        assert restored.claims.peer_id == proof.claims.peer_id
        assert restored.signature_b64 == proof.signature_b64


class TestAuthProofVerification:
    """Tests for verify_auth_proof()."""

    def test_valid_proof_passes(self, identity):
        """A freshly created proof must pass verification."""
        proof = create_auth_proof(identity)
        assert verify_auth_proof(proof)

    def test_wrong_scope_rejected(self, identity):
        """Query-scope proof must not satisfy admin requirement."""
        proof = create_auth_proof(identity, scope=SCOPE_QUERY)
        assert not verify_auth_proof(proof, required_scope=SCOPE_ADMIN)

    def test_admin_satisfies_query(self, identity):
        """Admin-scope proof must satisfy query-level requirement."""
        proof = create_auth_proof(identity, scope=SCOPE_ADMIN)
        assert verify_auth_proof(proof, required_scope=SCOPE_QUERY)

    def test_expired_proof_rejected(self, identity):
        """Proof with old timestamp must be rejected."""
        proof = create_auth_proof(identity)
        proof.claims.issued_at = time.time() - 400  # beyond default 300s TTL
        assert not verify_auth_proof(proof, max_age_seconds=300.0)

    def test_future_proof_rejected(self, identity):
        """Proof with far-future timestamp must be rejected."""
        proof = create_auth_proof(identity)
        proof.claims.issued_at = time.time() + 3600
        assert not verify_auth_proof(proof)

    def test_replay_rejected(self, identity):
        """Same proof submitted twice must be rejected second time."""
        proof = create_auth_proof(identity)
        seen_nonces: set[str] = set()
        assert verify_auth_proof(proof, seen_nonces=seen_nonces)
        assert not verify_auth_proof(proof, seen_nonces=seen_nonces)

    def test_tampered_signature_rejected(self, identity):
        """Altering the signature must cause verification to fail."""
        proof = create_auth_proof(identity)
        sig_bytes = bytearray(base64.b64decode(proof.signature_b64))
        sig_bytes[0] ^= 0xFF
        proof.signature_b64 = base64.b64encode(bytes(sig_bytes)).decode()
        assert not verify_auth_proof(proof)

    def test_tampered_claims_rejected(self, identity):
        """Changing a claim after signing must fail verification."""
        proof = create_auth_proof(identity)
        proof.claims.scope = SCOPE_ADMIN  # tamper
        assert not verify_auth_proof(proof)

    def test_missing_pubkey_rejected(self, identity):
        """Proof without ed25519_pubkey_b64 must be rejected."""
        proof = create_auth_proof(identity)
        proof.claims.ed25519_pubkey_b64 = ""
        assert not verify_auth_proof(proof)

    def test_polygon_id_type_rejected(self, identity):
        """polygon_id_zkp proof type must be rejected (not yet implemented)."""
        proof = create_auth_proof(identity)
        proof.proof_type = "polygon_id_zkp"
        assert not verify_auth_proof(proof)

    def test_topic_check_passes_when_covered(self, identity):
        """Proof covering a topic must pass topic-level check."""
        proof = create_auth_proof(
            identity, allowed_topics=["/aura/query/1.0.0", "/aura/admin/1.0.0"]
        )
        assert verify_auth_proof(proof, required_topic="/aura/query/1.0.0")

    def test_topic_check_fails_when_not_covered(self, identity):
        """Proof missing a required topic must be rejected."""
        proof = create_auth_proof(identity, allowed_topics=["/aura/query/1.0.0"])
        assert not verify_auth_proof(proof, required_topic="/aura/admin/1.0.0")
