"""
Zero-Knowledge Proof authorization for AURA queries.

Phase 3 used a simple Ed25519 auth_sig as a placeholder.
Phase 4 promotes this to a proper signed assertion system with:
  - AuthClaims: structured claim set (peer_id, timestamp, allowed_topics, scope)
  - AuthProof:  Ed25519 signature over the canonical JSON serialisation of claims
  - Challenge/response: ephemeral nonce prevents replay even with same claims

Future upgrade path (Phase 5+):
  Swap verify_auth_proof() for Polygon ID's SDK once it supports Python 3.14:
    from polygon_id import CredentialRequest, verify_zkp_proof
  The rest of the calling code does not need to change — only this module.

Polygon ID integration notes:
  - SDK: https://github.com/0xPolygonID/py-id  (Python 3.12 as of 2026)
  - Claims map to W3C Verifiable Credentials (vc/v1 context)
  - ZKP circuit: AtomicQuerySigV2 or AtomicQueryMTPV2
  - Proof type: Groth16 BN128
  - Issuer DID: node's did:key or did:polygonid
"""
import base64
import json
import os
import time
from dataclasses import dataclass, field

from backend.network.peer import PeerIdentity, verify_signature
from backend.utils.logging import get_logger

log = get_logger(__name__)

# Claim validity window in seconds
_CLAIM_TTL = 300

# Allowed scope values
SCOPE_QUERY = "query"
SCOPE_ADMIN = "admin"


@dataclass
class AuthClaims:
    """
    Structured set of claims included in an auth proof.

    Attributes:
        peer_id: The claimant's libp2p peer_id.
        issued_at: Unix timestamp when the proof was created.
        nonce: Random 16-byte hex string for replay protection.
        scope: Access scope ('query' | 'admin').
        allowed_topics: List of P2P topics the claimant is authorised for.
        ed25519_pubkey_b64: Claimant's Ed25519 public key for verification.
    """
    peer_id: str
    issued_at: float
    nonce: str
    scope: str = SCOPE_QUERY
    allowed_topics: list[str] = field(default_factory=lambda: ["/aura/query/1.0.0"])
    ed25519_pubkey_b64: str = ""

    def to_canonical_bytes(self) -> bytes:
        """Deterministic JSON serialisation for signing/verification."""
        return json.dumps(
            {
                "peer_id": self.peer_id,
                "issued_at": f"{self.issued_at:.6f}",
                "nonce": self.nonce,
                "scope": self.scope,
                "allowed_topics": sorted(self.allowed_topics),
                "ed25519_pubkey_b64": self.ed25519_pubkey_b64,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


@dataclass
class AuthProof:
    """
    Signed authorization proof.

    Attributes:
        claims: The AuthClaims being asserted.
        signature_b64: Ed25519 signature over claims.to_canonical_bytes().
        proof_type: 'ed25519_assertion' (current) or 'polygon_id_zkp' (future).
    """
    claims: AuthClaims
    signature_b64: str
    proof_type: str = "ed25519_assertion"

    def to_dict(self) -> dict:
        """Serialise proof to a wire-format dict."""
        return {
            "proof_type": self.proof_type,
            "claims": {
                "peer_id": self.claims.peer_id,
                "issued_at": self.claims.issued_at,
                "nonce": self.claims.nonce,
                "scope": self.claims.scope,
                "allowed_topics": self.claims.allowed_topics,
                "ed25519_pubkey_b64": self.claims.ed25519_pubkey_b64,
            },
            "signature_b64": self.signature_b64,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AuthProof":
        """Deserialise proof from a wire-format dict."""
        c = data["claims"]
        claims = AuthClaims(
            peer_id=c["peer_id"],
            issued_at=float(c["issued_at"]),
            nonce=c["nonce"],
            scope=c.get("scope", SCOPE_QUERY),
            allowed_topics=c.get("allowed_topics", ["/aura/query/1.0.0"]),
            ed25519_pubkey_b64=c.get("ed25519_pubkey_b64", ""),
        )
        return cls(
            claims=claims,
            signature_b64=data["signature_b64"],
            proof_type=data.get("proof_type", "ed25519_assertion"),
        )


# ── Public API ────────────────────────────────────────────────────────────────

def create_auth_proof(
    identity: PeerIdentity,
    scope: str = SCOPE_QUERY,
    allowed_topics: list[str] | None = None,
) -> AuthProof:
    """
    Create a signed authorization proof for this node.

    Args:
        identity: The node's PeerIdentity (signing key).
        scope: Access scope string.
        allowed_topics: Topics this proof authorises. Defaults to query topic.

    Returns:
        AuthProof signed with the node's Ed25519 key.
    """
    topics = allowed_topics or ["/aura/query/1.0.0"]
    claims = AuthClaims(
        peer_id=identity.peer_id,
        issued_at=time.time(),
        nonce=os.urandom(16).hex(),
        scope=scope,
        allowed_topics=topics,
        ed25519_pubkey_b64=identity.ed25519_pubkey_b64,
    )
    sig = identity.sign(claims.to_canonical_bytes())
    proof = AuthProof(
        claims=claims,
        signature_b64=base64.b64encode(sig).decode(),
    )
    log.debug("Created auth proof for peer %s (scope=%s)", identity.peer_id[:16], scope)
    return proof


def verify_auth_proof(
    proof: AuthProof,
    required_scope: str = SCOPE_QUERY,
    required_topic: str | None = None,
    max_age_seconds: float = _CLAIM_TTL,
    seen_nonces: set[str] | None = None,
) -> bool:
    """
    Verify an AuthProof for authenticity, freshness, scope, and replay protection.

    Checks:
      1. Proof type is supported.
      2. Signature is valid Ed25519.
      3. Claims are not expired (issued_at within max_age_seconds).
      4. Nonce has not been seen before (if seen_nonces is provided).
      5. Required scope is present.
      6. Required topic is in allowed_topics (if specified).

    Args:
        proof: The AuthProof to verify.
        required_scope: Minimum scope required ('query' or 'admin').
        required_topic: Specific topic the proof must cover.
        max_age_seconds: Maximum acceptable claim age.
        seen_nonces: Set of previously seen nonces for replay protection.

    Returns:
        True if the proof passes all checks.
    """
    # ── 1. Proof type ──────────────────────────────────────────────────────────
    if proof.proof_type == "polygon_id_zkp":
        # Polygon ID ZKP verification hook — not yet implemented for Python 3.14
        log.warning("Polygon ID ZKP verification not yet available; rejecting.")
        return False

    if proof.proof_type != "ed25519_assertion":
        log.warning("Unsupported proof type: %s", proof.proof_type)
        return False

    claims = proof.claims

    # ── 2. Timestamp freshness ─────────────────────────────────────────────────
    age = time.time() - claims.issued_at
    if age < -10 or age > max_age_seconds:
        log.warning("Auth proof expired or future-dated (age=%.1f s)", age)
        return False

    # ── 3. Replay nonce ────────────────────────────────────────────────────────
    if seen_nonces is not None:
        if claims.nonce in seen_nonces:
            log.warning("Auth proof nonce replay: %s", claims.nonce)
            return False
        seen_nonces.add(claims.nonce)

    # ── 4. Signature ───────────────────────────────────────────────────────────
    pubkey_b64 = claims.ed25519_pubkey_b64
    if not pubkey_b64:
        log.warning("Auth proof missing ed25519_pubkey_b64")
        return False

    if not verify_signature(proof.signature_b64, claims.to_canonical_bytes(), pubkey_b64):
        log.warning("Auth proof signature verification failed for peer %s", claims.peer_id[:16])
        return False

    # ── 5. Scope ───────────────────────────────────────────────────────────────
    scope_levels = {SCOPE_QUERY: 0, SCOPE_ADMIN: 1}
    if scope_levels.get(claims.scope, -1) < scope_levels.get(required_scope, 0):
        log.warning(
            "Insufficient scope: have=%s required=%s", claims.scope, required_scope
        )
        return False

    # ── 6. Topic ───────────────────────────────────────────────────────────────
    if required_topic and required_topic not in claims.allowed_topics:
        log.warning("Auth proof does not cover topic %s", required_topic)
        return False

    log.debug("Auth proof verified for peer %s", claims.peer_id[:16])
    return True


def extract_auth_proof_from_envelope_payload(payload: dict) -> AuthProof | None:
    """
    Extract an AuthProof from a decrypted envelope payload dict, if present.

    Args:
        payload: Decrypted message body dict.

    Returns:
        AuthProof or None if not present / invalid.
    """
    proof_data = payload.get("auth_proof")
    if not proof_data:
        return None
    try:
        return AuthProof.from_dict(proof_data)
    except Exception as exc:
        log.warning("Failed to parse auth_proof from payload: %s", exc)
        return None
