"""
Unit tests for backend.security.model_manifest.
Covers: manifest creation, signature verification, tamper detection, serialisation.
"""
import base64
import time

import pytest

from backend.network.peer import PeerIdentity
from backend.security.model_manifest import (
    ModelManifest,
    create_manifest,
    store_manifest,
    load_manifest,
    verify_manifest,
)


@pytest.fixture
def identity():
    return PeerIdentity.ephemeral()


async def _make_manifest(identity, model="llama3.2:3b") -> ModelManifest:
    """Helper to create a manifest (async, skips Ollama daemon lookup)."""
    return await create_manifest(identity, model_name=model, ollama_tag=model)


class TestManifestCreation:
    """Tests for create_manifest()."""

    @pytest.mark.asyncio
    async def test_creates_manifest_with_correct_peer_id(self, identity):
        """Manifest must carry the signing node's peer_id."""
        m = await _make_manifest(identity)
        assert m.peer_id == identity.peer_id

    @pytest.mark.asyncio
    async def test_has_non_empty_signature(self, identity):
        """Manifest must carry a non-empty signature."""
        m = await _make_manifest(identity)
        assert len(m.signature_b64) > 0
        base64.b64decode(m.signature_b64)  # must not raise

    @pytest.mark.asyncio
    async def test_has_correct_model_name(self, identity):
        """Manifest must store the provided model name."""
        m = await _make_manifest(identity, model="mistral:7b")
        assert m.model_name == "mistral:7b"
        assert m.ollama_tag == "mistral:7b"

    @pytest.mark.asyncio
    async def test_version_is_1(self, identity):
        """Manifest version must be 1."""
        m = await _make_manifest(identity)
        assert m.version == 1

    @pytest.mark.asyncio
    async def test_serialise_roundtrip(self, identity):
        """Manifest.to_dict() / from_dict() must be lossless."""
        m = await _make_manifest(identity)
        restored = ModelManifest.from_dict(m.to_dict())
        assert restored.peer_id == m.peer_id
        assert restored.signature_b64 == m.signature_b64
        assert restored.ollama_tag == m.ollama_tag


class TestManifestVerification:
    """Tests for verify_manifest()."""

    @pytest.mark.asyncio
    async def test_valid_manifest_passes(self, identity):
        """Freshly created manifest must pass verification."""
        m = await _make_manifest(identity)
        assert verify_manifest(m)

    @pytest.mark.asyncio
    async def test_tampered_model_name_fails(self, identity):
        """Altering model_name after signing must fail."""
        m = await _make_manifest(identity)
        m.model_name = "evil-model"
        assert not verify_manifest(m)

    @pytest.mark.asyncio
    async def test_tampered_peer_id_fails(self, identity):
        """Altering peer_id after signing must fail."""
        m = await _make_manifest(identity)
        m.peer_id = "fake_peer_id"
        assert not verify_manifest(m)

    @pytest.mark.asyncio
    async def test_tampered_signature_fails(self, identity):
        """Corrupting the signature must fail verification."""
        m = await _make_manifest(identity)
        sig_bytes = bytearray(base64.b64decode(m.signature_b64))
        sig_bytes[0] ^= 0xFF
        m.signature_b64 = base64.b64encode(bytes(sig_bytes)).decode()
        assert not verify_manifest(m)

    @pytest.mark.asyncio
    async def test_wrong_pubkey_fails(self, identity):
        """Manifest signed by A must fail verification if pubkey is B's."""
        other = PeerIdentity.ephemeral()
        m = await _make_manifest(identity)
        m.ed25519_pubkey_b64 = other.ed25519_pubkey_b64
        assert not verify_manifest(m)


class TestManifestCompatibility:
    """Tests for ModelManifest.is_compatible_with()."""

    @pytest.mark.asyncio
    async def test_same_tag_is_compatible(self, identity):
        """Two manifests with the same Ollama tag must be compatible."""
        a = await _make_manifest(identity, model="llama3.2:3b")
        b = await _make_manifest(identity, model="llama3.2:3b")
        assert a.is_compatible_with(b)

    @pytest.mark.asyncio
    async def test_different_tags_incompatible(self, identity):
        """Different model tags must be incompatible."""
        a = await _make_manifest(identity, model="llama3.2:3b")
        b = await _make_manifest(identity, model="mistral:7b")
        assert not a.is_compatible_with(b)


class TestManifestPersistence:
    """Tests for store_manifest() and load_manifest()."""

    @pytest.mark.asyncio
    async def test_store_and_load_roundtrip(self, identity, tmp_path):
        """Manifest stored and reloaded must be identical."""
        m = await _make_manifest(identity)
        path = tmp_path / "manifest.json"
        store_manifest(m, path)
        loaded = load_manifest(path)
        assert loaded is not None
        assert loaded.peer_id == m.peer_id
        assert loaded.signature_b64 == m.signature_b64

    def test_load_missing_returns_none(self, tmp_path):
        """Loading a non-existent manifest file must return None."""
        result = load_manifest(tmp_path / "ghost.json")
        assert result is None
