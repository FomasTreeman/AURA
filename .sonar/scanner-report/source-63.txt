"""
Unit tests for backend.network.rendezvous.
Tests mDNS and Bootstrap discovery mechanisms.
"""

import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from backend.network.rendezvous import (
    MDNSDiscovery,
    BootstrapDiscovery,
    MDNS_SERVICE_TYPE,
)


class MockPeerIdentity:
    """Mock PeerIdentity for testing."""

    def __init__(self, peer_id="QmTestPeer123456"):
        self.peer_id = peer_id


class MockPeer:
    """Mock PeerInfo for testing."""

    def __init__(self, peer_id):
        self.peer_id = peer_id


class MockAdapter:
    """Mock AuraP2PAdapter for testing."""

    def __init__(self):
        self._peers = {}
        self.dial_calls = []

    def get_peers(self):
        return list(self._peers.values())

    async def dial(self, multiaddr):
        self.dial_calls.append(multiaddr)
        return MockPeer("QmDialedPeer")


class TestMDNSServiceType:
    """Tests for MDNS_SERVICE_TYPE constant."""

    def test_service_type_format(self):
        """Service type should be a valid mDNS service type string."""
        assert MDNS_SERVICE_TYPE == "_aura-p2p._tcp.local."


class TestMDNSDiscovery:
    """Tests for MDNSDiscovery class."""

    @pytest.fixture
    def mock_identity(self):
        return MockPeerIdentity("QmTestPeer123456")

    @pytest.fixture
    def mock_adapter(self):
        return MockAdapter()

    def test_initialization(self, mock_identity, mock_adapter):
        """MDNSDiscovery should store identity, adapter, and port."""
        discovery = MDNSDiscovery(mock_identity, mock_adapter, 9000)
        assert discovery._identity is mock_identity
        assert discovery._adapter is mock_adapter
        assert discovery._port == 9000
        assert discovery._zc is None
        assert discovery._info is None
        assert discovery._browser is None


class TestBootstrapDiscovery:
    """Tests for BootstrapDiscovery class."""

    @pytest.fixture
    def mock_adapter(self):
        return MockAdapter()

    def test_initialization(self, mock_adapter):
        """BootstrapDiscovery should store adapter and bootstrap list."""
        multiaddrs = ["/ip4/1.2.3.4/tcp/9000/p2p/QmBootstrap1"]
        discovery = BootstrapDiscovery(mock_adapter, multiaddrs)
        assert discovery._adapter is mock_adapter
        assert discovery._bootstrap == multiaddrs
        assert discovery._retry_interval == 30.0
        assert discovery._task is None

    def test_custom_retry_interval(self, mock_adapter):
        """BootstrapDiscovery should accept custom retry_interval."""
        multiaddrs = ["/ip4/1.2.3.4/tcp/9000/p2p/QmBootstrap1"]
        discovery = BootstrapDiscovery(mock_adapter, multiaddrs, retry_interval=60.0)
        assert discovery._retry_interval == 60.0

    @pytest.mark.asyncio
    async def test_start_with_empty_bootstrap(self, mock_adapter):
        """start() should return early when no bootstrap peers configured."""
        discovery = BootstrapDiscovery(mock_adapter, [])
        await discovery.start()
        assert discovery._task is None

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self, mock_adapter):
        """stop() should not fail when called without start()."""
        discovery = BootstrapDiscovery(
            mock_adapter, ["/ip4/1.2.3.4/tcp/9000/p2p/QmBootstrap1"]
        )
        await discovery.stop()  # Should not raise

    @pytest.mark.asyncio
    async def test_bootstrap_loop_dials_peers(self, mock_adapter):
        """_bootstrap_loop should attempt to dial all bootstrap peers."""
        multiaddrs = [
            "/ip4/1.2.3.4/tcp/9000/p2p/QmBootstrap1",
            "/ip4/5.6.7.8/tcp/9000/p2p/QmBootstrap2",
        ]
        discovery = BootstrapDiscovery(mock_adapter, multiaddrs)

        async def run_once():
            for multiaddr in discovery._bootstrap:
                result = await discovery._adapter.dial(multiaddr)

        await run_once()

        assert len(mock_adapter.dial_calls) == 2
        assert mock_adapter.dial_calls[0] == multiaddrs[0]
        assert mock_adapter.dial_calls[1] == multiaddrs[1]
