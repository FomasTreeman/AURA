"""
Peer discovery for AURA P2P network.

Two mechanisms:
1. mDNS (zeroconf) – discovers peers on the same LAN automatically.
2. Bootstrap – connects to a static list of bootstrap multiaddrs on startup.

Both mechanisms feed discovered peers into the AuraP2PAdapter via dial().
"""
import asyncio
import socket
from typing import TYPE_CHECKING

from zeroconf import ServiceBrowser, ServiceInfo, Zeroconf
from zeroconf.asyncio import AsyncZeroconf

from backend.network.peer import PeerIdentity
from backend.utils.logging import get_logger

if TYPE_CHECKING:
    from backend.network.libp2p_adapter import AuraP2PAdapter

log = get_logger(__name__)

MDNS_SERVICE_TYPE = "_aura-p2p._tcp.local."


class MDNSDiscovery:
    """
    Advertises this node on the LAN and discovers other AURA nodes via mDNS.

    Uses the zeroconf library to:
    - Register a service of type _aura-p2p._tcp.local. with the node's peer_id.
    - Browse for other nodes of the same type and dial them via the adapter.
    """

    def __init__(
        self,
        identity: PeerIdentity,
        adapter: "AuraP2PAdapter",
        port: int,
    ) -> None:
        self._identity = identity
        self._adapter = adapter
        self._port = port
        self._zc: AsyncZeroconf | None = None
        self._info: ServiceInfo | None = None
        self._browser: ServiceBrowser | None = None

    async def start(self) -> None:
        """Register mDNS service and start browsing for peers."""
        self._zc = AsyncZeroconf()

        hostname = socket.gethostname()
        service_name = f"{self._identity.peer_id[:16]}.{MDNS_SERVICE_TYPE}"

        self._info = ServiceInfo(
            type_=MDNS_SERVICE_TYPE,
            name=service_name,
            port=self._port,
            properties={
                "peer_id": self._identity.peer_id,
                "version": "1.0",
            },
            server=f"{hostname}.local.",
        )

        await self._zc.async_register_service(self._info)
        log.info(
            "mDNS: registered service '%s' on port %d",
            service_name,
            self._port,
        )

        # Browse for other AURA nodes
        self._browser = ServiceBrowser(
            self._zc.zeroconf,
            MDNS_SERVICE_TYPE,
            handlers=[self._on_service_state_change],
        )
        log.info("mDNS: browsing for peers on %s", MDNS_SERVICE_TYPE)

    async def stop(self) -> None:
        """Unregister mDNS service and stop browsing."""
        if self._zc:
            if self._info:
                await self._zc.async_unregister_service(self._info)
            await self._zc.async_close()
            self._zc = None
        log.info("mDNS: stopped.")

    def _on_service_state_change(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change,
    ) -> None:
        """Handle a discovered/removed mDNS service."""
        from zeroconf import ServiceStateChange

        if state_change is ServiceStateChange.Added:
            asyncio.create_task(self._connect_discovered(zeroconf, service_type, name))

    async def _connect_discovered(
        self, zeroconf: Zeroconf, service_type: str, name: str
    ) -> None:
        """Resolve and connect to a newly discovered mDNS peer."""
        info = ServiceInfo(service_type, name)
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: info.request(zeroconf, 3000),
        )

        if not info.parsed_addresses():
            return

        addr = info.parsed_addresses()[0]
        port = info.port
        peer_id = (info.properties or {}).get(b"peer_id", b"").decode()

        # Don't connect to ourselves
        if peer_id == self._identity.peer_id:
            return

        multiaddr = f"/ip4/{addr}/tcp/{port}/p2p/{peer_id}"
        log.info("mDNS: discovered peer at %s", multiaddr)

        # Avoid duplicate connections
        existing = [p.peer_id for p in self._adapter.get_peers()]
        if peer_id in existing:
            return

        result = await self._adapter.dial(multiaddr)
        if result:
            log.info("mDNS: connected to %s", result.peer_id[:16])


class BootstrapDiscovery:
    """
    Connects to a static list of bootstrap multiaddrs on node startup.

    This provides internet-wide peer discovery when mDNS is not available.
    """

    def __init__(
        self,
        adapter: "AuraP2PAdapter",
        bootstrap_multiaddrs: list[str],
        retry_interval: float = 30.0,
    ) -> None:
        self._adapter = adapter
        self._bootstrap = bootstrap_multiaddrs
        self._retry_interval = retry_interval
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Begin connecting to bootstrap peers and periodically retry."""
        if not self._bootstrap:
            log.info("Bootstrap: no bootstrap peers configured.")
            return
        self._task = asyncio.create_task(self._bootstrap_loop())
        log.info("Bootstrap: connecting to %d bootstrap peers", len(self._bootstrap))

    async def stop(self) -> None:
        """Cancel the bootstrap loop."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _bootstrap_loop(self) -> None:
        """Try to connect to all bootstrap peers, retry periodically."""
        while True:
            for multiaddr in self._bootstrap:
                existing_ids = [p.peer_id for p in self._adapter.get_peers()]
                # Only dial if not already connected
                try:
                    from backend.network.peer import parse_multiaddr
                    _, _, target_peer_id = parse_multiaddr(multiaddr)
                    if target_peer_id in existing_ids:
                        continue
                except Exception:
                    pass

                result = await self._adapter.dial(multiaddr)
                if result:
                    log.info(
                        "Bootstrap: connected to %s", result.peer_id[:16]
                    )

            await asyncio.sleep(self._retry_interval)
