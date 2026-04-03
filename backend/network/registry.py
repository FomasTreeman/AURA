"""
In-memory rendezvous registry.

Peers register their advertised multiaddr here on startup and refresh it
periodically (heartbeat). Other nodes query this registry to discover peers
they haven't connected to yet.

Entries expire after TTL seconds if not refreshed, so crashed / silently
disconnected nodes are eventually evicted.
"""
import time
from dataclasses import dataclass, field

from backend.utils.logging import get_logger

log = get_logger(__name__)

_DEFAULT_TTL = 300.0  # seconds – must be refreshed faster than this


@dataclass
class RegistryEntry:
    peer_id: str
    multiaddr: str
    registered_at: float = field(default_factory=time.time)

    def refresh(self) -> None:
        self.registered_at = time.time()

    def is_alive(self, ttl: float) -> bool:
        return (time.time() - self.registered_at) < ttl


class RendezvousRegistry:
    """Thread-safe (asyncio-safe) in-memory peer registry."""

    def __init__(self, ttl: float = _DEFAULT_TTL) -> None:
        self._ttl = ttl
        self._entries: dict[str, RegistryEntry] = {}

    def register(self, peer_id: str, multiaddr: str) -> None:
        """Upsert a peer entry, resetting its TTL clock."""
        if peer_id in self._entries:
            self._entries[peer_id].multiaddr = multiaddr
            self._entries[peer_id].refresh()
        else:
            self._entries[peer_id] = RegistryEntry(peer_id=peer_id, multiaddr=multiaddr)
        log.debug("Rendezvous: registered %s at %s", peer_id[:16], multiaddr)

    def unregister(self, peer_id: str) -> None:
        """Remove a peer entry immediately."""
        if self._entries.pop(peer_id, None):
            log.debug("Rendezvous: unregistered %s", peer_id[:16])

    def peers(self, exclude_peer_id: str | None = None) -> list[dict]:
        """Return all live entries, optionally excluding a specific peer."""
        self._evict_expired()
        return [
            {"peer_id": e.peer_id, "multiaddr": e.multiaddr}
            for e in self._entries.values()
            if e.peer_id != exclude_peer_id
        ]

    def _evict_expired(self) -> None:
        expired = [k for k, v in self._entries.items() if not v.is_alive(self._ttl)]
        for k in expired:
            log.debug("Rendezvous: evicting expired entry %s", k[:16])
            del self._entries[k]


# Module-level singleton shared by the FastAPI endpoints and lifespan startup.
RENDEZVOUS_REGISTRY = RendezvousRegistry()
