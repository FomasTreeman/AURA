"""
Unit tests for backend.network.peer.
Covers: keypair generation, PeerID derivation, sign/verify, multiaddr parsing, DID export.
"""
import base64

import pytest

from backend.network.peer import (
    PeerIdentity,
    PeerInfo,
    parse_multiaddr,
    verify_signature,
)


class TestPeerIdentityCreation:
    """Tests for PeerIdentity key generation."""

    def test_ephemeral_creates_identity(self):
        """PeerIdentity.ephemeral() must produce a valid identity."""
        identity = PeerIdentity.ephemeral()
        assert identity.peer_id
        assert len(identity.peer_id) > 10

    def test_peer_id_is_deterministic(self, tmp_path):
        """Same key file produces the same peer_id on each load."""
        id1 = PeerIdentity.load_or_create(tmp_path / "keys")
        id2 = PeerIdentity.load_or_create(tmp_path / "keys")
        assert id1.peer_id == id2.peer_id

    def test_different_identities_have_different_peer_ids(self):
        """Two ephemeral identities must have different peer_ids."""
        a = PeerIdentity.ephemeral()
        b = PeerIdentity.ephemeral()
        assert a.peer_id != b.peer_id

    def test_peer_id_is_base58(self):
        """PeerID must be base58btc-encoded (no 0, O, I, l characters)."""
        identity = PeerIdentity.ephemeral()
        invalid_chars = set("0OIl")
        assert not any(c in invalid_chars for c in identity.peer_id), (
            f"PeerID contains invalid base58 chars: {identity.peer_id}"
        )

    def test_pubkeys_are_base64(self):
        """Ed25519 and X25519 public key fields must be valid base64."""
        identity = PeerIdentity.ephemeral()
        # Should not raise
        ed_bytes = base64.b64decode(identity.ed25519_pubkey_b64)
        x_bytes = base64.b64decode(identity.x25519_pubkey_b64)
        assert len(ed_bytes) == 32   # Ed25519 pub key is 32 bytes
        assert len(x_bytes) == 32    # X25519 pub key is 32 bytes

    def test_load_or_create_persists_keys(self, tmp_path):
        """Keys are saved to disk and loaded correctly on second call."""
        key_dir = tmp_path / "identity"
        id1 = PeerIdentity.load_or_create(key_dir)
        id2 = PeerIdentity.load_or_create(key_dir)
        assert id1.peer_id == id2.peer_id
        assert id1.ed25519_pubkey_b64 == id2.ed25519_pubkey_b64


class TestSignVerify:
    """Tests for Ed25519 signing and verification."""

    def test_sign_verify_roundtrip(self):
        """Data signed by identity A should verify correctly."""
        identity = PeerIdentity.ephemeral()
        data = b"hello aura p2p"
        sig = identity.sign(data)
        sig_b64 = base64.b64encode(sig).decode()
        assert verify_signature(sig_b64, data, identity.ed25519_pubkey_b64)

    def test_wrong_pubkey_rejected(self):
        """Signature from identity A must not verify against identity B's pubkey."""
        a = PeerIdentity.ephemeral()
        b = PeerIdentity.ephemeral()
        data = b"test data"
        sig = a.sign(data)
        sig_b64 = base64.b64encode(sig).decode()
        assert not verify_signature(sig_b64, data, b.ed25519_pubkey_b64)

    def test_tampered_data_rejected(self):
        """Altering the signed data must invalidate the signature."""
        identity = PeerIdentity.ephemeral()
        data = b"original message"
        sig = identity.sign(data)
        sig_b64 = base64.b64encode(sig).decode()
        assert not verify_signature(sig_b64, b"tampered message", identity.ed25519_pubkey_b64)

    def test_tampered_signature_rejected(self):
        """A corrupted signature byte must be rejected."""
        identity = PeerIdentity.ephemeral()
        data = b"valid data"
        sig = bytearray(identity.sign(data))
        sig[0] ^= 0xFF  # flip first byte
        sig_b64 = base64.b64encode(bytes(sig)).decode()
        assert not verify_signature(sig_b64, data, identity.ed25519_pubkey_b64)

    def test_empty_signature_rejected(self):
        """An empty signature must be rejected without crashing."""
        identity = PeerIdentity.ephemeral()
        assert not verify_signature("", b"data", identity.ed25519_pubkey_b64)


class TestPeerInfo:
    """Tests for PeerInfo creation and serialisation."""

    def test_peer_info_multiaddr_format(self):
        """peer_info() must produce a correctly formatted multiaddr."""
        identity = PeerIdentity.ephemeral()
        info = identity.peer_info(host="127.0.0.1", port=9000)
        assert f"/p2p/{identity.peer_id}" in info.multiaddrs[0]
        assert "/ip4/" in info.multiaddrs[0]
        assert "/tcp/9000" in info.multiaddrs[0]

    def test_peer_info_serialise_roundtrip(self):
        """PeerInfo.to_dict() / from_dict() must be lossless."""
        identity = PeerIdentity.ephemeral()
        original = identity.peer_info("10.0.0.1", 9001)
        restored = PeerInfo.from_dict(original.to_dict())
        assert restored.peer_id == original.peer_id
        assert restored.multiaddrs == original.multiaddrs
        assert restored.ed25519_pubkey_b64 == original.ed25519_pubkey_b64
        assert restored.x25519_pubkey_b64 == original.x25519_pubkey_b64

    def test_did_export_structure(self):
        """DID document must contain required W3C fields."""
        identity = PeerIdentity.ephemeral()
        did = identity.export_did()
        assert "@context" in did
        assert did["id"].startswith("did:key:")
        assert "verificationMethod" in did
        assert len(did["verificationMethod"]) == 1
        assert did["verificationMethod"][0]["type"] == "Ed25519VerificationKey2020"


class TestParseMultiaddr:
    """Tests for parse_multiaddr()."""

    def test_valid_multiaddr(self):
        """Should correctly parse a well-formed multiaddr."""
        host, port, peer_id = parse_multiaddr("/ip4/1.2.3.4/tcp/9000/p2p/QmSomePeerID")
        assert host == "1.2.3.4"
        assert port == 9000
        assert peer_id == "QmSomePeerID"

    def test_localhost_multiaddr(self):
        """Should parse localhost addresses."""
        host, port, peer_id = parse_multiaddr("/ip4/127.0.0.1/tcp/9001/p2p/TestPeerXYZ")
        assert host == "127.0.0.1"
        assert port == 9001

    def test_invalid_multiaddr_raises(self):
        """Malformed multiaddr must raise ValueError."""
        with pytest.raises(ValueError):
            parse_multiaddr("/not/a/valid/addr")

    def test_roundtrip_from_peer_info(self):
        """Multiaddr built from peer_info() should parse back correctly."""
        identity = PeerIdentity.ephemeral()
        info = identity.peer_info("192.168.1.5", 9999)
        host, port, peer_id = parse_multiaddr(info.multiaddrs[0])
        assert host == "192.168.1.5"
        assert port == 9999
        assert peer_id == identity.peer_id
