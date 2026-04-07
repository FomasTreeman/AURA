"""
Unit tests for backend.security.did.
Covers: keystore creation/loading, encryption/decryption, key rotation, wrong passphrase.
"""
import json

import pytest

from backend.security.did import (
    DIDKeystore,
    KeyRotationRecord,
    create_keystore,
    load_keystore,
    rotate_key,
    verify_rotation_chain,
)
from backend.network.peer import PeerIdentity


class TestKeystoreCreation:
    """Tests for create_keystore()."""

    def test_creates_file_on_disk(self, tmp_path):
        """create_keystore writes a JSON file to disk."""
        ks_path = tmp_path / "keystore.json"
        create_keystore(ks_path, passphrase="test-pass")
        assert ks_path.exists()

    def test_file_is_valid_json(self, tmp_path):
        """The keystore file must be valid JSON."""
        ks_path = tmp_path / "ks.json"
        create_keystore(ks_path, passphrase="test-pass")
        data = json.loads(ks_path.read_text())
        assert data["version"] == 1
        assert "ed25519" in data
        assert "x25519" in data
        assert "peer_id" in data

    def test_returns_did_keystore(self, tmp_path):
        """create_keystore returns a DIDKeystore instance."""
        ks = create_keystore(tmp_path / "ks.json", "pass")
        assert isinstance(ks, DIDKeystore)
        assert ks.peer_id

    def test_did_has_correct_prefix(self, tmp_path):
        """DID must start with 'did:key:'."""
        ks = create_keystore(tmp_path / "ks.json", "pass")
        assert ks.did.startswith("did:key:")

    def test_private_seeds_are_encrypted(self, tmp_path):
        """The stored seeds must be encrypted, not plaintext."""
        ks_path = tmp_path / "ks.json"
        ks = create_keystore(ks_path, "my-pass")
        data = json.loads(ks_path.read_text())
        # The seed should not appear as a 32-byte raw hex value in the ct_b64 field
        from backend.security.did import _encrypt_seed
        ed_seed, x_seed = ks.identity.export_seeds()
        # Verify the ct is NOT the plaintext seed
        assert data["ed25519"]["ct_b64"] != ed_seed.hex()

    def test_did_document_export(self, tmp_path):
        """DID document must have required W3C fields."""
        ks = create_keystore(tmp_path / "ks.json", "pass")
        doc = ks.export_did_document()
        assert "@context" in doc
        assert doc["id"].startswith("did:key:")
        assert "verificationMethod" in doc


class TestKeystoreLoading:
    """Tests for load_keystore()."""

    def test_load_round_trip(self, tmp_path):
        """Keystore saved and reloaded must produce the same peer_id."""
        ks_path = tmp_path / "ks.json"
        original = create_keystore(ks_path, "my-passphrase")
        loaded = load_keystore(ks_path, "my-passphrase")
        assert loaded.peer_id == original.peer_id
        assert loaded.identity.ed25519_pubkey_b64 == original.identity.ed25519_pubkey_b64

    def test_wrong_passphrase_raises(self, tmp_path):
        """Loading with a wrong passphrase must raise ValueError."""
        ks_path = tmp_path / "ks.json"
        create_keystore(ks_path, "correct-pass")
        with pytest.raises(ValueError, match="decryption failed"):
            load_keystore(ks_path, "wrong-pass")

    def test_missing_file_raises(self, tmp_path):
        """Loading a non-existent path must raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_keystore(tmp_path / "ghost.json", "pass")

    def test_loaded_identity_can_sign(self, tmp_path):
        """Loaded identity must be able to sign data."""
        ks_path = tmp_path / "ks.json"
        create_keystore(ks_path, "pass123")
        ks = load_keystore(ks_path, "pass123")
        sig = ks.identity.sign(b"test data")
        assert len(sig) == 64

    def test_loaded_identity_signature_verifies(self, tmp_path):
        """Signature from loaded identity must verify with its public key."""
        from backend.network.peer import verify_signature
        import base64
        ks_path = tmp_path / "ks.json"
        create_keystore(ks_path, "pass")
        ks = load_keystore(ks_path, "pass")
        data = b"sign this"
        sig_b64 = base64.b64encode(ks.identity.sign(data)).decode()
        assert verify_signature(sig_b64, data, ks.identity.ed25519_pubkey_b64)


class TestKeyRotation:
    """Tests for rotate_key()."""

    def test_rotation_changes_peer_id(self, tmp_path):
        """After rotation, the peer_id must change."""
        ks_path = tmp_path / "ks.json"
        old_ks = create_keystore(ks_path, "pass")
        new_ks = rotate_key(old_ks, "pass")
        assert new_ks.peer_id != old_ks.peer_id

    def test_rotation_appends_history(self, tmp_path):
        """Rotation must add the old peer_id to rotation_history."""
        ks_path = tmp_path / "ks.json"
        old_ks = create_keystore(ks_path, "pass")
        old_id = old_ks.peer_id
        new_ks = rotate_key(old_ks, "pass")
        assert len(new_ks.rotation_history) == 1
        assert new_ks.rotation_history[0].old_peer_id == old_id

    def test_rotation_history_has_signature(self, tmp_path):
        """Each rotation record must carry a non-empty signature."""
        ks_path = tmp_path / "ks.json"
        old_ks = create_keystore(ks_path, "pass")
        new_ks = rotate_key(old_ks, "pass")
        assert new_ks.rotation_history[0].rotation_sig

    def test_double_rotation_accumulates_history(self, tmp_path):
        """Two rotations must produce two history records."""
        ks_path = tmp_path / "ks.json"
        ks1 = create_keystore(ks_path, "pass")
        ks2 = rotate_key(ks1, "pass")
        ks3 = rotate_key(ks2, "pass")
        assert len(ks3.rotation_history) == 2

    def test_rotation_with_new_passphrase(self, tmp_path):
        """Rotated keystore can be loaded with the new passphrase."""
        ks_path = tmp_path / "ks.json"
        old_ks = create_keystore(ks_path, "old-pass")
        rotate_key(old_ks, "old-pass", new_passphrase="new-pass")
        loaded = load_keystore(ks_path, "new-pass")
        assert loaded.peer_id

    def test_verify_rotation_chain_no_history(self, tmp_path):
        """Keystore with no rotation history must pass chain verification."""
        ks = create_keystore(tmp_path / "ks.json", "pass")
        assert verify_rotation_chain(ks)

    def test_verify_rotation_chain_with_history(self, tmp_path):
        """Keystore with valid rotation history must pass chain verification."""
        ks_path = tmp_path / "ks.json"
        ks = create_keystore(ks_path, "pass")
        ks2 = rotate_key(ks, "pass")
        assert verify_rotation_chain(ks2)

    def test_keystore_path_required_for_rotation(self):
        """Rotation without a keystore_path must raise ValueError."""
        ks = DIDKeystore(identity=PeerIdentity.ephemeral())
        with pytest.raises(ValueError, match="path not set"):
            rotate_key(ks, "pass")
