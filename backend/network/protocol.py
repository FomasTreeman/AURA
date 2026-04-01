"""
AURA P2P message protocol.

Every message sent over the P2P network is wrapped in an Envelope that:
  1. Is signed with the sender's Ed25519 key (integrity + authenticity).
  2. Has its body encrypted with X25519 ECDH + AES-256-GCM (confidentiality).
  3. Carries a random nonce + timestamp for replay protection.

Wire format (JSON):
  {
    "version": "1.0",
    "type":    "query_request" | "query_response" | "peer_announce",
    "from":    {"peer_id": "...", "ed25519_pubkey_b64": "...", "x25519_pubkey_b64": "..."},
    "nonce":   "<base64-16-bytes>",
    "ts":      1234567890.123,          // Unix timestamp (float)
    "body":    "<base64-encrypted-json>",
    "sig":     "<base64-ed25519-64-byte-signature>"
  }

Signature covers: version + type + peer_id + nonce + ts + body (all as UTF-8).
"""
import base64
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from backend.network.peer import PeerIdentity, PeerInfo, verify_signature
from backend.utils.logging import get_logger

log = get_logger(__name__)

PROTOCOL_VERSION = "1.0"
NONCE_BYTES = 16
AES_KEY_BYTES = 32
GCM_NONCE_BYTES = 12


class MessageType(str, Enum):
    """Supported P2P message types."""

    QUERY_REQUEST = "query_request"
    QUERY_RESPONSE = "query_response"
    PEER_ANNOUNCE = "peer_announce"


@dataclass
class Envelope:
    """
    A signed, optionally-encrypted P2P message envelope.

    All fields are as transmitted on the wire (strings, base64 where appropriate).
    """

    version: str
    type: MessageType
    from_peer: dict           # {peer_id, ed25519_pubkey_b64, x25519_pubkey_b64}
    nonce: str                # base64-encoded 16-byte random nonce
    ts: float                 # Unix timestamp
    body: str                 # base64-encoded JSON (encrypted or plaintext)
    sig: str                  # base64-encoded 64-byte Ed25519 signature

    # ── Serialisation ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialise to a wire-format dict."""
        return {
            "version": self.version,
            "type": self.type.value if isinstance(self.type, MessageType) else self.type,
            "from": self.from_peer,
            "nonce": self.nonce,
            "ts": self.ts,
            "body": self.body,
            "sig": self.sig,
        }

    def to_bytes(self) -> bytes:
        """Serialise to JSON bytes."""
        return json.dumps(self.to_dict(), separators=(",", ":")).encode()

    @classmethod
    def from_dict(cls, data: dict) -> "Envelope":
        """Deserialise from a wire-format dict."""
        return cls(
            version=data["version"],
            type=MessageType(data["type"]),
            from_peer=data["from"],
            nonce=data["nonce"],
            ts=float(data["ts"]),
            body=data["body"],
            sig=data["sig"],
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> "Envelope":
        """Parse JSON bytes into an Envelope."""
        return cls.from_dict(json.loads(raw))

    # ── Signature material ─────────────────────────────────────────────────────

    def _signable(self) -> bytes:
        """
        Produce the canonical byte string that is signed/verified.

        Covers all fields except 'sig' itself.
        """
        parts = "|".join([
            self.version,
            self.type.value if isinstance(self.type, MessageType) else self.type,
            self.from_peer.get("peer_id", ""),
            self.nonce,
            f"{self.ts:.6f}",
            self.body,
        ])
        return parts.encode("utf-8")


# ── Encryption helpers ────────────────────────────────────────────────────────

def _derive_session_key(
    local_x25519_priv: X25519PrivateKey,
    remote_x25519_pub_b64: str,
    info: bytes = b"aura-p2p-v1",
) -> bytes:
    """
    Perform X25519 ECDH and derive a 32-byte AES session key via HKDF-SHA256.

    Args:
        local_x25519_priv: Local X25519 private key.
        remote_x25519_pub_b64: Base64-encoded remote X25519 public key.
        info: HKDF context string.

    Returns:
        32-byte AES-256 key.
    """
    remote_pub_bytes = base64.b64decode(remote_x25519_pub_b64)
    remote_pub = X25519PublicKey.from_public_bytes(remote_pub_bytes)
    shared_secret = local_x25519_priv.exchange(remote_pub)
    return HKDF(
        algorithm=SHA256(),
        length=AES_KEY_BYTES,
        salt=None,
        info=info,
    ).derive(shared_secret)


def encrypt_body(
    payload: dict,
    local_x25519_priv: X25519PrivateKey,
    recipient_x25519_pub_b64: str,
) -> str:
    """
    Encrypt a dict payload for a specific recipient using X25519 ECDH + AES-256-GCM.

    The output is a base64-encoded blob containing:
      [12-byte GCM nonce] + [ciphertext + 16-byte auth tag]

    Args:
        payload: Dict to encrypt (will be JSON-serialised).
        local_x25519_priv: Sender's X25519 private key.
        recipient_x25519_pub_b64: Recipient's base64 X25519 public key.

    Returns:
        Base64-encoded encrypted body string.
    """
    session_key = _derive_session_key(local_x25519_priv, recipient_x25519_pub_b64)
    aes = AESGCM(session_key)
    nonce = os.urandom(GCM_NONCE_BYTES)
    plaintext = json.dumps(payload, separators=(",", ":")).encode()
    ciphertext = aes.encrypt(nonce, plaintext, None)
    return base64.b64encode(nonce + ciphertext).decode()


def decrypt_body(
    encrypted_b64: str,
    local_x25519_priv: X25519PrivateKey,
    sender_x25519_pub_b64: str,
) -> dict:
    """
    Decrypt an encrypted body using X25519 ECDH + AES-256-GCM.

    Args:
        encrypted_b64: Base64-encoded encrypted body from an Envelope.
        local_x25519_priv: Recipient's X25519 private key.
        sender_x25519_pub_b64: Sender's base64 X25519 public key.

    Returns:
        Decrypted dict payload.

    Raises:
        ValueError: If decryption fails (wrong key, tampered data, bad format).
    """
    try:
        raw = base64.b64decode(encrypted_b64)
        gcm_nonce = raw[:GCM_NONCE_BYTES]
        ciphertext = raw[GCM_NONCE_BYTES:]
        session_key = _derive_session_key(local_x25519_priv, sender_x25519_pub_b64)
        aes = AESGCM(session_key)
        plaintext = aes.decrypt(gcm_nonce, ciphertext, None)
        return json.loads(plaintext)
    except Exception as exc:
        raise ValueError(f"Body decryption failed: {exc}") from exc


def encode_body_plain(payload: dict) -> str:
    """Base64-encode a plaintext payload (no encryption — used for peer_announce)."""
    return base64.b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode()


def decode_body_plain(body_b64: str) -> dict:
    """Decode a plaintext base64-encoded body."""
    return json.loads(base64.b64decode(body_b64))


# ── Envelope factory ──────────────────────────────────────────────────────────

def create_envelope(
    msg_type: MessageType,
    identity: PeerIdentity,
    payload: dict,
    recipient_x25519_pub_b64: str | None = None,
) -> Envelope:
    """
    Create a signed Envelope, optionally encrypting the body for a recipient.

    For peer_announce messages (no recipient), body is plaintext base64.
    For query_request / query_response, body is encrypted with recipient's X25519 key.

    Args:
        msg_type: Type of message.
        identity: Sender's PeerIdentity.
        payload: Message payload dict.
        recipient_x25519_pub_b64: Recipient's X25519 public key for encryption.
                                   If None, body is stored as plaintext base64.

    Returns:
        Signed Envelope ready to transmit.
    """
    nonce = base64.b64encode(os.urandom(NONCE_BYTES)).decode()
    ts = time.time()

    if recipient_x25519_pub_b64 is not None:
        body = encrypt_body(payload, identity.x25519_private, recipient_x25519_pub_b64)
    else:
        body = encode_body_plain(payload)

    envelope = Envelope(
        version=PROTOCOL_VERSION,
        type=msg_type,
        from_peer={
            "peer_id": identity.peer_id,
            "ed25519_pubkey_b64": identity.ed25519_pubkey_b64,
            "x25519_pubkey_b64": identity.x25519_pubkey_b64,
        },
        nonce=nonce,
        ts=ts,
        body=body,
        sig="",  # placeholder
    )

    sig_bytes = identity.sign(envelope._signable())
    envelope.sig = base64.b64encode(sig_bytes).decode()
    return envelope


# ── Envelope verification ─────────────────────────────────────────────────────

def verify_envelope(
    envelope: Envelope,
    nonce_cache: set[str],
    max_age_seconds: float = 300.0,
) -> bool:
    """
    Validate an incoming Envelope for authenticity, integrity, and freshness.

    Checks:
      1. Signature is valid (Ed25519).
      2. Timestamp is within max_age_seconds (replay TTL).
      3. Nonce has not been seen before (replay deduplication).
      4. Protocol version is supported.

    Args:
        envelope: The Envelope to verify.
        nonce_cache: Set of previously seen nonces (mutated in-place on success).
        max_age_seconds: Maximum acceptable message age in seconds.

    Returns:
        True if the envelope passes all checks.
    """
    # Version check
    if envelope.version != PROTOCOL_VERSION:
        log.warning("Rejected envelope: unsupported version '%s'", envelope.version)
        return False

    # Timestamp freshness
    age = time.time() - envelope.ts
    if age < -10 or age > max_age_seconds:
        log.warning(
            "Rejected envelope: timestamp out of window (age=%.1f s)", age
        )
        return False

    # Nonce replay check
    if envelope.nonce in nonce_cache:
        log.warning("Rejected envelope: nonce replay detected (%s)", envelope.nonce)
        return False

    # Signature verification
    ed25519_pubkey_b64 = envelope.from_peer.get("ed25519_pubkey_b64", "")
    if not verify_signature(envelope.sig, envelope._signable(), ed25519_pubkey_b64):
        log.warning(
            "Rejected envelope: invalid signature from peer %s",
            envelope.from_peer.get("peer_id", "unknown"),
        )
        return False

    # Accept: record nonce
    nonce_cache.add(envelope.nonce)
    return True
