"""
Unit tests for backend.network.registry (RendezvousRegistry).
No external dependencies — pure in-memory logic.
"""
import time

import pytest

from backend.network.registry import RegistryEntry, RendezvousRegistry


# ── RegistryEntry ─────────────────────────────────────────────────────────────

class TestRegistryEntry:
    def test_is_alive_within_ttl(self):
        entry = RegistryEntry(peer_id="p1", multiaddr="/ip4/1.2.3.4/tcp/9000/p2p/p1")
        assert entry.is_alive(ttl=300)

    def test_is_alive_expired(self):
        entry = RegistryEntry(peer_id="p1", multiaddr="/ip4/1.2.3.4/tcp/9000/p2p/p1")
        entry.registered_at = time.time() - 400
        assert not entry.is_alive(ttl=300)

    def test_refresh_resets_clock(self):
        entry = RegistryEntry(peer_id="p1", multiaddr="/ip4/1.2.3.4/tcp/9000/p2p/p1")
        entry.registered_at = time.time() - 400
        entry.refresh()
        assert entry.is_alive(ttl=300)


# ── RendezvousRegistry ────────────────────────────────────────────────────────

class TestRegister:
    def setup_method(self):
        self.registry = RendezvousRegistry(ttl=300)

    def test_register_adds_entry(self):
        self.registry.register("peer1", "/ip4/1.2.3.4/tcp/9000/p2p/peer1")
        peers = self.registry.peers()
        assert any(p["peer_id"] == "peer1" for p in peers)

    def test_register_upserts_multiaddr(self):
        self.registry.register("peer1", "/ip4/1.2.3.4/tcp/9000/p2p/peer1")
        self.registry.register("peer1", "/ip4/5.6.7.8/tcp/9000/p2p/peer1")
        peers = self.registry.peers()
        assert len(peers) == 1
        assert peers[0]["multiaddr"] == "/ip4/5.6.7.8/tcp/9000/p2p/peer1"

    def test_register_resets_ttl(self):
        self.registry.register("peer1", "/ip4/1.2.3.4/tcp/9000/p2p/peer1")
        # Manually expire it
        self.registry._entries["peer1"].registered_at = time.time() - 400
        # Re-register resets the clock
        self.registry.register("peer1", "/ip4/1.2.3.4/tcp/9000/p2p/peer1")
        assert self.registry._entries["peer1"].is_alive(ttl=300)

    def test_multiple_peers_registered(self):
        for i in range(5):
            self.registry.register(f"peer{i}", f"/ip4/1.2.3.{i}/tcp/9000/p2p/peer{i}")
        assert len(self.registry.peers()) == 5


class TestUnregister:
    def setup_method(self):
        self.registry = RendezvousRegistry(ttl=300)

    def test_unregister_removes_entry(self):
        self.registry.register("peer1", "/ip4/1.2.3.4/tcp/9000")
        self.registry.unregister("peer1")
        assert not any(p["peer_id"] == "peer1" for p in self.registry.peers())

    def test_unregister_unknown_peer_is_noop(self):
        """Unregistering a peer that was never registered must not raise."""
        self.registry.unregister("ghost-peer")

    def test_unregister_only_removes_target(self):
        self.registry.register("peer1", "/ip4/1.1.1.1/tcp/9000")
        self.registry.register("peer2", "/ip4/2.2.2.2/tcp/9000")
        self.registry.unregister("peer1")
        peers = self.registry.peers()
        assert len(peers) == 1
        assert peers[0]["peer_id"] == "peer2"


class TestPeers:
    def setup_method(self):
        self.registry = RendezvousRegistry(ttl=300)

    def test_peers_returns_all_live(self):
        self.registry.register("p1", "/ip4/1.1.1.1/tcp/9000")
        self.registry.register("p2", "/ip4/2.2.2.2/tcp/9000")
        assert len(self.registry.peers()) == 2

    def test_peers_excludes_self(self):
        self.registry.register("p1", "/ip4/1.1.1.1/tcp/9000")
        self.registry.register("p2", "/ip4/2.2.2.2/tcp/9000")
        result = self.registry.peers(exclude_peer_id="p1")
        assert len(result) == 1
        assert result[0]["peer_id"] == "p2"

    def test_peers_empty_registry(self):
        assert self.registry.peers() == []

    def test_peers_evicts_expired(self):
        self.registry.register("stale", "/ip4/1.1.1.1/tcp/9000")
        self.registry._entries["stale"].registered_at = time.time() - 400
        self.registry.register("fresh", "/ip4/2.2.2.2/tcp/9000")
        peers = self.registry.peers()
        peer_ids = [p["peer_id"] for p in peers]
        assert "stale" not in peer_ids
        assert "fresh" in peer_ids

    def test_peers_returns_dicts_with_required_keys(self):
        self.registry.register("peer1", "/ip4/1.1.1.1/tcp/9000")
        for p in self.registry.peers():
            assert "peer_id" in p
            assert "multiaddr" in p


class TestTTLEviction:
    def test_short_ttl_evicts_quickly(self):
        registry = RendezvousRegistry(ttl=0.01)  # 10ms TTL
        registry.register("fast-expire", "/ip4/1.1.1.1/tcp/9000")
        time.sleep(0.05)
        assert registry.peers() == []

    def test_eviction_does_not_affect_fresh_entries(self):
        registry = RendezvousRegistry(ttl=0.01)
        registry.register("old", "/ip4/1.1.1.1/tcp/9000")
        time.sleep(0.05)
        registry.register("new", "/ip4/2.2.2.2/tcp/9000")
        peers = registry.peers()
        assert len(peers) == 1
        assert peers[0]["peer_id"] == "new"
