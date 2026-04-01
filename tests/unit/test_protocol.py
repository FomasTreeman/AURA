"""
Unit tests for backend.network.protocol.
Covers: envelope creation/verification, body encryption/decryption, replay protection,
signature tamper detection, version validation.
"""
import base64
import json
import time

import pytest

from backend.network.peer import PeerIdentity
from backend.network.protocol import (
    Envelope,
    MessageType,
    create_envelope,
    decode_body_plain,
    decrypt_body,
    encode_body_plain,
    encrypt_body,
    verify_envelope,
)


@pytest.fixture
def alice():
    """Ephemeral peer identity for test sender."""
    return PeerIdentity.ephemeral()


@pytest.fixture
def bob():
    """Ephemeral peer identity for test recipient."""
    return PeerIdentity.ephemeral()


class TestEnvelopeCreation:
    """Tests for create_envelope()."""

    def test_creates_all_required_fields(self, alice):
        """Envelope must contain all wire-format fields."""
        env = create_envelope(
            MessageType.PEER_ANNOUNCE,
            alice,
            {"hello": "world"},
        )
        assert env.version == "1.0"
        assert env.type == MessageType.PEER_ANNOUNCE
        assert env.from_peer.get("peer_id") == alice.peer_id
        assert env.nonce
        assert env.ts > 0
        assert env.body
        assert env.sig

    def test_signature_is_non_empty(self, alice):
        """The sig field must be a non-empty base64 string."""
        env = create_envelope(MessageType.QUERY_REQUEST, alice, {"q": "test"})
        assert len(env.sig) > 0
        base64.b64decode(env.sig)  # must not raise

    def test_peer_announce_body_is_plaintext(self, alice):
        """peer_announce envelopes (no recipient) must have a decodable plaintext body."""
        payload = {"type": "peer_announce", "host": "node.local"}
        env = create_envelope(MessageType.PEER_ANNOUNCE, alice, payload)
        decoded = decode_body_plain(env.body)
        assert decoded == payload

    def test_encrypted_body_is_not_plaintext(self, alice, bob):
        """When a recipient key is provided, body must NOT be plaintext-decodable."""
        payload = {"question": "What is AURA?"}
        env = create_envelope(
            MessageType.QUERY_REQUEST,
            alice,
            payload,
            recipient_x25519_pub_b64=bob.x25519_pubkey_b64,
        )
        # Body should NOT equal the plaintext base64 of the payload
        plaintext_b64 = encode_body_plain(payload)
        assert env.body != plaintext_b64

    def test_two_envelopes_have_different_nonces(self, alice):
        """Each envelope must carry a fresh random nonce."""
        env1 = create_envelope(MessageType.PEER_ANNOUNCE, alice, {"x": 1})
        env2 = create_envelope(MessageType.PEER_ANNOUNCE, alice, {"x": 1})
        assert env1.nonce != env2.nonce

    def test_serialise_roundtrip(self, alice):
        """Envelope.to_bytes() / Envelope.from_bytes() must be lossless."""
        env = create_envelope(MessageType.PEER_ANNOUNCE, alice, {"key": "value"})
        restored = Envelope.from_bytes(env.to_bytes())
        assert restored.version == env.version
        assert restored.type == env.type
        assert restored.nonce == env.nonce
        assert restored.sig == env.sig
        assert restored.body == env.body


class TestEnvelopeVerification:
    """Tests for verify_envelope()."""

    def test_valid_envelope_passes(self, alice):
        """A freshly created valid envelope must pass verification."""
        env = create_envelope(MessageType.PEER_ANNOUNCE, alice, {"ok": True})
        nonce_cache: set[str] = set()
        assert verify_envelope(env, nonce_cache)

    def test_accepted_nonce_is_cached(self, alice):
        """After acceptance, the nonce must be in the cache."""
        env = create_envelope(MessageType.PEER_ANNOUNCE, alice, {"ok": True})
        nonce_cache: set[str] = set()
        verify_envelope(env, nonce_cache)
        assert env.nonce in nonce_cache

    def test_replay_rejected(self, alice):
        """The same envelope submitted twice must be rejected on the second attempt."""
        env = create_envelope(MessageType.PEER_ANNOUNCE, alice, {"ok": True})
        nonce_cache: set[str] = set()
        assert verify_envelope(env, nonce_cache)
        assert not verify_envelope(env, nonce_cache), "Replay not detected"

    def test_wrong_version_rejected(self, alice):
        """Envelopes with an unsupported version string must be rejected."""
        env = create_envelope(MessageType.PEER_ANNOUNCE, alice, {})
        env.version = "99.0"
        nonce_cache: set[str] = set()
        assert not verify_envelope(env, nonce_cache)

    def test_future_timestamp_rejected(self, alice):
        """Envelopes with timestamps far in the future must be rejected."""
        env = create_envelope(MessageType.PEER_ANNOUNCE, alice, {})
        env.ts = time.time() + 3600  # 1 hour in the future
        nonce_cache: set[str] = set()
        assert not verify_envelope(env, nonce_cache)

    def test_expired_timestamp_rejected(self, alice):
        """Envelopes older than max_age_seconds must be rejected."""
        env = create_envelope(MessageType.PEER_ANNOUNCE, alice, {})
        env.ts = time.time() - 400  # older than default 300s TTL
        nonce_cache: set[str] = set()
        assert not verify_envelope(env, nonce_cache, max_age_seconds=300.0)

    def test_tampered_body_rejected(self, alice):
        """Altering the body after signing must cause signature verification to fail."""
        env = create_envelope(MessageType.PEER_ANNOUNCE, alice, {"data": "original"})
        env.body = encode_body_plain({"data": "TAMPERED"})  # mutate body
        nonce_cache: set[str] = set()
        assert not verify_envelope(env, nonce_cache)

    def test_tampered_sig_rejected(self, alice):
        """A corrupted signature must be rejected."""
        env = create_envelope(MessageType.PEER_ANNOUNCE, alice, {"x": 1})
        sig_bytes = bytearray(base64.b64decode(env.sig))
        sig_bytes[0] ^= 0xFF
        env.sig = base64.b64encode(bytes(sig_bytes)).decode()
        nonce_cache: set[str] = set()
        assert not verify_envelope(env, nonce_cache)

    def test_wrong_sender_pubkey_rejected(self, alice, bob):
        """Replacing the from.ed25519_pubkey_b64 with a different peer's key must fail."""
        env = create_envelope(MessageType.PEER_ANNOUNCE, alice, {})
        # Swap in bob's pubkey — signature was made by alice
        env.from_peer["ed25519_pubkey_b64"] = bob.ed25519_pubkey_b64
        nonce_cache: set[str] = set()
        assert not verify_envelope(env, nonce_cache)


class TestBodyEncryption:
    """Tests for encrypt_body() and decrypt_body()."""

    def test_roundtrip(self, alice, bob):
        """Encrypting with alice's key for bob must decrypt correctly with bob's key."""
        payload = {"secret": "AURA RAG result", "chunks": 3}
        encrypted = encrypt_body(
            payload,
            alice.x25519_private,
            bob.x25519_pubkey_b64,
        )
        decrypted = decrypt_body(
            encrypted,
            bob.x25519_private,
            alice.x25519_pubkey_b64,
        )
        assert decrypted == payload

    def test_wrong_recipient_key_raises(self, alice, bob):
        """Decrypting with the wrong key (alice trying to decrypt her own encrypted msg) must fail."""
        eve = PeerIdentity.ephemeral()
        payload = {"msg": "confidential"}
        encrypted = encrypt_body(payload, alice.x25519_private, bob.x25519_pubkey_b64)
        with pytest.raises(ValueError):
            decrypt_body(encrypted, eve.x25519_private, alice.x25519_pubkey_b64)

    def test_tampered_ciphertext_raises(self, alice, bob):
        """Flipping a byte in the ciphertext must cause AESGCM auth tag failure."""
        payload = {"q": "sensitive query"}
        encrypted_b64 = encrypt_body(payload, alice.x25519_private, bob.x25519_pubkey_b64)
        raw = bytearray(base64.b64decode(encrypted_b64))
        raw[-1] ^= 0xFF  # corrupt last byte (auth tag)
        tampered = base64.b64encode(bytes(raw)).decode()
        with pytest.raises(ValueError):
            decrypt_body(tampered, bob.x25519_private, alice.x25519_pubkey_b64)

    def test_different_nonces_produce_different_ciphertexts(self, alice, bob):
        """Two encryptions of the same payload must produce different ciphertexts (random GCM nonce)."""
        payload = {"x": 42}
        c1 = encrypt_body(payload, alice.x25519_private, bob.x25519_pubkey_b64)
        c2 = encrypt_body(payload, alice.x25519_private, bob.x25519_pubkey_b64)
        assert c1 != c2  # different GCM nonces → different ciphertext


class TestMessageTypeEnum:
    """Tests for the MessageType enum."""

    def test_all_types_have_string_values(self):
        """All message types must have the expected string values."""
        assert MessageType.QUERY_REQUEST.value == "query_request"
        assert MessageType.QUERY_RESPONSE.value == "query_response"
        assert MessageType.PEER_ANNOUNCE.value == "peer_announce"

    def test_from_string(self):
        """MessageType can be constructed from a string value."""
        assert MessageType("query_request") == MessageType.QUERY_REQUEST
