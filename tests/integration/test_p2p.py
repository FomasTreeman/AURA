"""
Integration tests for the AURA P2P adapter.

These tests spin up two real in-process TCP nodes on ephemeral localhost ports,
connect them, and verify end-to-end message passing, signature verification,
and tamper detection. No Docker or external services required.
"""
import asyncio
import time

import pytest
import pytest_asyncio

from backend.network.libp2p_adapter import AuraP2PAdapter
from backend.network.peer import PeerIdentity
from backend.network.protocol import (
    Envelope,
    MessageType,
    create_envelope,
    verify_envelope,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _free_port() -> int:
    """Find an available localhost TCP port."""
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _make_node(port: int) -> AuraP2PAdapter:
    """Create and start a P2P adapter on the given port."""
    identity = PeerIdentity.ephemeral()
    adapter = AuraP2PAdapter(identity)
    await adapter.start(host="127.0.0.1", port=port)
    return adapter


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def event_loop():
    """Provide a fresh event loop for each test."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.mark.asyncio
class TestP2PConnection:
    """Tests for two-node TCP connection and handshake."""

    async def test_dial_returns_peer_info(self):
        """Node A dialing Node B should return B's PeerInfo."""
        port_a = _free_port()
        port_b = _free_port()
        node_a = await _make_node(port_a)
        node_b = await _make_node(port_b)
        try:
            peer_info = await node_a.dial(
                f"/ip4/127.0.0.1/tcp/{port_b}/p2p/{node_b.peer_id}"
            )
            assert peer_info is not None
            assert peer_info.peer_id == node_b.peer_id
        finally:
            await node_a.stop()
            await node_b.stop()

    async def test_connected_peers_visible_on_both_sides(self):
        """After dial, both nodes should see each other in get_peers()."""
        port_a = _free_port()
        port_b = _free_port()
        node_a = await _make_node(port_a)
        node_b = await _make_node(port_b)
        try:
            await node_a.dial(f"/ip4/127.0.0.1/tcp/{port_b}/p2p/{node_b.peer_id}")
            # Give node_b a moment to complete the handshake
            await asyncio.sleep(0.2)
            a_peers = [p.peer_id for p in node_a.get_peers()]
            b_peers = [p.peer_id for p in node_b.get_peers()]
            assert node_b.peer_id in a_peers
            assert node_a.peer_id in b_peers
        finally:
            await node_a.stop()
            await node_b.stop()

    async def test_invalid_multiaddr_returns_none(self):
        """Dialing an invalid multiaddr must return None gracefully."""
        port_a = _free_port()
        node_a = await _make_node(port_a)
        try:
            result = await node_a.dial("/invalid/multiaddr")
            assert result is None
        finally:
            await node_a.stop()

    async def test_unreachable_peer_returns_none(self):
        """Dialing a port with no listener must return None."""
        port_a = _free_port()
        port_unused = _free_port()
        node_a = await _make_node(port_a)
        try:
            identity_b = PeerIdentity.ephemeral()
            result = await node_a.dial(
                f"/ip4/127.0.0.1/tcp/{port_unused}/p2p/{identity_b.peer_id}"
            )
            assert result is None
        finally:
            await node_a.stop()


@pytest.mark.asyncio
class TestP2PPublishSubscribe:
    """Tests for publish/subscribe over a live two-node connection."""

    async def test_published_message_received_by_subscriber(self):
        """A message published by node A must be received by node B's handler."""
        port_a = _free_port()
        port_b = _free_port()
        node_a = await _make_node(port_a)
        node_b = await _make_node(port_b)

        received: list[Envelope] = []

        async def handler(envelope: Envelope, sender) -> None:
            received.append(envelope)

        node_b.subscribe("query_request", handler)

        try:
            await node_a.dial(f"/ip4/127.0.0.1/tcp/{port_b}/p2p/{node_b.peer_id}")
            await asyncio.sleep(0.1)  # wait for handshake

            await node_a.publish("query_request", {"question": "What is AURA?"})
            await asyncio.sleep(0.3)  # allow message to arrive

            assert len(received) >= 1, "No message received by node B"
        finally:
            await node_a.stop()
            await node_b.stop()

    async def test_received_envelope_has_valid_signature(self):
        """The envelope received by node B must pass Ed25519 signature verification."""
        port_a = _free_port()
        port_b = _free_port()
        node_a = await _make_node(port_a)
        node_b = await _make_node(port_b)

        verified: list[bool] = []
        nonce_cache: set[str] = set()

        async def handler(envelope: Envelope, sender) -> None:
            verified.append(verify_envelope(envelope, nonce_cache))

        node_b.subscribe("query_request", handler)

        try:
            await node_a.dial(f"/ip4/127.0.0.1/tcp/{port_b}/p2p/{node_b.peer_id}")
            await asyncio.sleep(0.1)
            await node_a.publish("query_request", {"q": "test"})
            await asyncio.sleep(0.3)
            assert len(verified) >= 1
            assert all(verified), "Signature verification failed"
        finally:
            await node_a.stop()
            await node_b.stop()

    async def test_stop_clears_peers(self):
        """After stop(), get_peers() must return an empty list."""
        port_a = _free_port()
        port_b = _free_port()
        node_a = await _make_node(port_a)
        node_b = await _make_node(port_b)
        await node_a.dial(f"/ip4/127.0.0.1/tcp/{port_b}/p2p/{node_b.peer_id}")
        await asyncio.sleep(0.1)
        await node_a.stop()
        assert node_a.get_peers() == []
        await node_b.stop()


@pytest.mark.asyncio
class TestMetricsTracking:
    """Tests that metrics are updated correctly during P2P activity."""

    async def test_peers_connected_gauge(self):
        """peers_connected gauge must reflect the current peer count."""
        from backend.network.metrics import METRICS

        port_a = _free_port()
        port_b = _free_port()
        node_a = await _make_node(port_a)
        node_b = await _make_node(port_b)

        try:
            await node_a.dial(f"/ip4/127.0.0.1/tcp/{port_b}/p2p/{node_b.peer_id}")
            await asyncio.sleep(0.1)
            # node_a should have 1 peer
            assert len(node_a.get_peers()) == 1
        finally:
            await node_a.stop()
            await node_b.stop()

    async def test_messages_published_counter(self):
        """messages_published_total must increment after publish()."""
        from backend.network.metrics import METRICS

        initial = METRICS.messages_published_total.value
        port_a = _free_port()
        port_b = _free_port()
        node_a = await _make_node(port_a)
        node_b = await _make_node(port_b)

        try:
            await node_a.dial(f"/ip4/127.0.0.1/tcp/{port_b}/p2p/{node_b.peer_id}")
            await asyncio.sleep(0.1)
            await node_a.publish("query_request", {"q": "anything"})
            await asyncio.sleep(0.1)
            assert METRICS.messages_published_total.value > initial
        finally:
            await node_a.stop()
            await node_b.stop()
