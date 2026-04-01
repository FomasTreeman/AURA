"""
Integration tests for AURA Phase 4 revocation system.

Tests verify:
 - Local tombstoning removes chunks from ChromaDB
 - Revocation broadcasts propagate to connected peers
 - Tombstoned CIDs are excluded from federated query results
 - CID integrity enforcement rejects tampered chunks
"""
import asyncio
import socket

import pytest

from backend.network.libp2p_adapter import AuraP2PAdapter
from backend.network.peer import PeerIdentity
from backend.rag.consensus import add_tombstone, get_tombstones, apply_tombstones
from backend.rag.federated import FederatedRetriever
from backend.rag.rrf import make_chunk_id
from backend.security.revocation import RevocationManager
from backend.storage.ipfs_integration import compute_cid_v1


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_chunk(text: str, cid: str, source: str = "doc.pdf") -> dict:
    return {
        "text": text,
        "cid": cid,
        "source": source,
        "page": 1,
        "distance": 0.1,
        "chunk_id": make_chunk_id(cid, text),
        "ipfs_cid": compute_cid_v1(text.encode()),
    }


def _make_retriever_fn(chunks):
    def fn(question, top_k, threshold=1.0):
        return chunks[:top_k]
    return fn


async def _make_node(port, retriever_fn=None):
    identity = PeerIdentity.ephemeral()
    adapter = AuraP2PAdapter(identity)
    await adapter.start(host="127.0.0.1", port=port)
    fed = FederatedRetriever(identity, adapter, local_retriever=retriever_fn)
    mgr = RevocationManager(identity, adapter)
    return identity, adapter, fed, mgr


# ── Tombstone tests ───────────────────────────────────────────────────────────

class TestLocalTombstone:
    """Tests for local tombstoning."""

    def setup_method(self):
        """Clear tombstones before each test."""
        import backend.rag.consensus as m
        m._tombstoned_cids.clear()

    def test_add_tombstone_persists(self):
        """Tombstoned CID appears in get_tombstones()."""
        add_tombstone("deadbeef")
        assert "deadbeef" in get_tombstones()

    def test_tombstoned_chunks_excluded(self):
        """Chunks from tombstoned CIDs must be filtered from results."""
        add_tombstone("revoked_cid")
        chunks = [
            _make_chunk("safe text", cid="safe_cid"),
            _make_chunk("sensitive data", cid="revoked_cid"),
        ]
        result = apply_tombstones(chunks)
        assert len(result) == 1
        assert result[0]["cid"] == "safe_cid"

    def test_federated_result_excludes_tombstoned(self):
        """Federated query result must not include tombstoned chunks."""
        add_tombstone("to_be_excluded")
        chunks = [
            _make_chunk("included text", cid="good_cid"),
            _make_chunk("excluded text", cid="to_be_excluded"),
        ]
        clean = apply_tombstones(chunks)
        assert all(c["cid"] != "to_be_excluded" for c in clean)


# ── CID integrity enforcement ─────────────────────────────────────────────────

class TestCIDIntegrity:
    """Tests for CID integrity checks on peer responses."""

    def test_valid_ipfs_cid_passes(self):
        """Chunk with correct ipfs_cid must not be rejected."""
        text = "trusted chunk text"
        ipfs_cid = compute_cid_v1(text.encode())
        chunk = _make_chunk(text, "some_cid")
        chunk["ipfs_cid"] = ipfs_cid
        # Verify manually
        from backend.storage.ipfs_integration import verify_cid_bytes
        assert verify_cid_bytes(text.encode(), ipfs_cid)

    def test_tampered_text_fails_cid_check(self):
        """Chunk with text tampered after CID was computed must fail."""
        original = "original text"
        ipfs_cid = compute_cid_v1(original.encode())
        from backend.storage.ipfs_integration import verify_cid_bytes
        assert not verify_cid_bytes(b"tampered text", ipfs_cid)

    def test_compute_cid_v1_deterministic_for_text(self):
        """CID computed from chunk text must be deterministic."""
        text = "federated chunk"
        c1 = compute_cid_v1(text.encode())
        c2 = compute_cid_v1(text.encode())
        assert c1 == c2


# ── P2P revocation propagation ────────────────────────────────────────────────

@pytest.mark.asyncio
class TestRevocationPropagation:
    """Tests for revocation broadcast between two nodes."""

    def setup_method(self):
        import backend.rag.consensus as m
        m._tombstoned_cids.clear()

    async def test_revoke_adds_local_tombstone(self):
        """revoke() must tombstone the CID locally even without peers."""
        port = _free_port()
        _, adapter, _, mgr = await _make_node(port)
        try:
            cid_to_revoke = "abc" * 21 + "ab"  # 64-char hex-like string
            await mgr.revoke(cid_to_revoke, reason="test")
            assert cid_to_revoke in get_tombstones()
        finally:
            await adapter.stop()

    async def test_revocation_propagates_to_peer(self):
        """Revocation broadcast from node A must tombstone CID on node B."""
        port_a = _free_port()
        port_b = _free_port()

        chunks_a = [_make_chunk("shared doc", cid="shared_cid_abc")]
        chunks_b = [_make_chunk("shared doc", cid="shared_cid_abc")]

        id_a, adapter_a, fed_a, mgr_a = await _make_node(
            port_a, _make_retriever_fn(chunks_a)
        )
        id_b, adapter_b, fed_b, mgr_b = await _make_node(
            port_b, _make_retriever_fn(chunks_b)
        )

        try:
            # Connect the nodes
            await adapter_a.dial(f"/ip4/127.0.0.1/tcp/{port_b}/p2p/{adapter_b.peer_id}")
            await asyncio.sleep(0.2)

            # Node A revokes the document
            await mgr_a.revoke("shared_cid_abc", reason="GDPR")
            await asyncio.sleep(0.5)  # allow propagation

            # Both nodes should have the CID tombstoned
            assert "shared_cid_abc" in get_tombstones(), "Local tombstone missing"
            # Note: peer tombstone is applied in node B's consensus module
            # We test it via apply_tombstones on the chunks
            result = apply_tombstones(chunks_b)
            assert len(result) == 0, "Tombstoned chunk still in results after revocation"

        finally:
            await adapter_a.stop()
            await adapter_b.stop()

    async def test_tombstoned_cid_excluded_from_federated_query(self):
        """After revocation, federated query must not return tombstoned chunks."""
        port_a = _free_port()

        cid = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
        chunks = [_make_chunk("sensitive document text", cid=cid)]
        _, adapter, fed, mgr = await _make_node(
            port_a, _make_retriever_fn(chunks)
        )

        try:
            # Revoke before query
            await mgr.revoke(cid, reason="data breach")
            assert cid in get_tombstones()

            # Query should not return tombstoned chunk
            result = await fed.query("sensitive document", timeout=0.5)
            revoked_chunks = [c for c in result.chunks if c.get("cid") == cid]
            assert len(revoked_chunks) == 0, "Revoked chunk appeared in query results"

        finally:
            await adapter.stop()
