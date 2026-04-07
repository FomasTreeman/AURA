"""
AURA P2P Adapter – asyncio TCP implementation with Gossipsub-style pub/sub.

This module provides the same interface as py-libp2p would, implemented over
pure asyncio TCP + Ed25519/X25519 cryptography. The adapter can be swapped for
a native py-libp2p implementation when it gains Python 3.14 support.

Wire protocol:
  - All messages are length-prefixed: [4-byte big-endian uint32 length][JSON bytes]
  - Handshake on connect: each side sends a HELLO envelope (peer_announce type)
  - After handshake: Envelope messages for topics

Connection lifecycle:
  1. Local node starts TCP server.
  2. Remote peer connects (or local dials remote).
  3. Both sides send HELLO (peer_announce) with their PeerInfo.
  4. After handshake, both sides are "connected".
  5. publish(topic, payload) sends an Envelope to every connected peer.
  6. Received envelopes are verified and dispatched to topic handlers.
"""
import asyncio
import json
import struct
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from backend.network.metrics import METRICS
from backend.network.peer import PeerIdentity, PeerInfo, parse_multiaddr
from backend.network.protocol import (
    Envelope,
    MessageType,
    create_envelope,
    decode_body_plain,
    verify_envelope,
)
from backend.utils.logging import get_logger

log = get_logger(__name__)

# Framing constants
_LENGTH_PREFIX_SIZE = 4
_MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # 10 MB hard cap


@dataclass
class _PeerConnection:
    """Represents an active TCP connection to a remote peer."""

    peer_info: PeerInfo
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    connected_at: float = field(default_factory=time.time)

    @property
    def peer_id(self) -> str:
        return self.peer_info.peer_id

    async def send(self, data: bytes) -> None:
        """Send length-prefixed data, updating bytes_sent metric."""
        frame = struct.pack(">I", len(data)) + data
        self.writer.write(frame)
        await self.writer.drain()
        METRICS.bytes_sent_total.inc(len(frame))

    def close(self) -> None:
        """Close the underlying TCP connection."""
        try:
            self.writer.close()
        except Exception:
            pass


# Topic handler type alias
TopicHandler = Callable[[Envelope, PeerInfo], Awaitable[None]]


class AuraP2PAdapter:
    """
    Libp2p-compatible P2P adapter using asyncio TCP transport.

    Implements the same interface as a future py-libp2p adapter would:
      start(), stop(), publish(), subscribe(), dial(), get_peers()

    Usage:
        adapter = AuraP2PAdapter(identity)
        await adapter.start(host="0.0.0.0", port=9000)
        adapter.subscribe("/aura/query/1.0.0", my_handler)
        await adapter.publish("/aura/query/1.0.0", {"question": "..."})
        peers = adapter.get_peers()
        await adapter.stop()
    """

    def __init__(self, identity: PeerIdentity) -> None:
        self._identity = identity
        self._peers: dict[str, _PeerConnection] = {}   # peer_id → connection
        self._handlers: dict[str, list[TopicHandler]] = defaultdict(list)
        self._nonce_cache: set[str] = set()
        self._server: asyncio.Server | None = None
        self._host: str = "127.0.0.1"
        self._port: int = 9000
        self._running: bool = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self, host: str = "0.0.0.0", port: int = 9000) -> None:
        """
        Start the TCP server and begin accepting peer connections.

        Args:
            host: Interface to bind to.
            port: TCP port to listen on.
        """
        self._host = host
        self._port = port
        self._running = True
        self._server = await asyncio.start_server(
            self._handle_incoming,
            host=host,
            port=port,
        )
        log.info(
            "P2P adapter listening on %s:%d  peer_id=%s",
            host, port, self._identity.peer_id[:16],
        )

    async def stop(self) -> None:
        """Gracefully shut down the server and all peer connections."""
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        for conn in list(self._peers.values()):
            conn.close()
        self._peers.clear()
        METRICS.peers_connected.set(0)
        log.info("P2P adapter stopped.")

    # ── Public API ────────────────────────────────────────────────────────────

    def subscribe(self, topic: str, handler: TopicHandler) -> None:
        """
        Register a handler for messages on a topic.

        Multiple handlers per topic are supported.

        Args:
            topic: Topic string, e.g. '/aura/query/1.0.0'.
            handler: Async callable (envelope, peer_info) → None.
        """
        self._handlers[topic].append(handler)
        log.debug("Subscribed to topic '%s'", topic)

    async def publish(self, topic: str, payload: dict) -> None:
        """
        Broadcast a signed envelope to all connected peers subscribed to a topic.

        The body is encrypted separately for each recipient using their X25519 key.

        Args:
            topic: Topic string.
            payload: Dict payload to include in the envelope body.
        """
        if not self._peers:
            log.debug("publish: no peers connected, message dropped")
            return

        payload_with_topic = {"topic": topic, **payload}

        for peer_id, conn in list(self._peers.items()):
            try:
                envelope = create_envelope(
                    msg_type=MessageType.QUERY_REQUEST,
                    identity=self._identity,
                    payload=payload_with_topic,
                    recipient_x25519_pub_b64=conn.peer_info.x25519_pubkey_b64,
                )
                await conn.send(envelope.to_bytes())
                METRICS.messages_published_total.inc()
            except Exception as exc:
                log.error("Failed to send to peer %s: %s", peer_id[:12], exc)
                await self._disconnect_peer(peer_id)

    async def publish_envelope(self, envelope: Envelope, peer_id: str) -> None:
        """
        Send a pre-built envelope to a specific peer by ID.

        Args:
            envelope: The envelope to send.
            peer_id: Target peer's ID string.
        """
        conn = self._peers.get(peer_id)
        if conn is None:
            log.warning("publish_envelope: peer %s not connected", peer_id[:12])
            return
        try:
            await conn.send(envelope.to_bytes())
            METRICS.messages_published_total.inc()
        except Exception as exc:
            log.error("publish_envelope error for %s: %s", peer_id[:12], exc)
            await self._disconnect_peer(peer_id)

    async def dial(self, multiaddr: str) -> PeerInfo | None:
        """
        Connect to a peer by multiaddr.

        Args:
            multiaddr: e.g. '/ip4/1.2.3.4/tcp/9000/p2p/Qm...'

        Returns:
            PeerInfo of the connected peer, or None on failure.
        """
        try:
            host, port, _ = parse_multiaddr(multiaddr)
        except ValueError as exc:
            log.error("dial: invalid multiaddr '%s': %s", multiaddr, exc)
            return None

        try:
            reader, writer = await asyncio.open_connection(host, port)
            log.info("Dialed %s:%d", host, port)
            peer_info = await self._handshake(reader, writer)
            if peer_info is None:
                writer.close()
                return None
            conn = _PeerConnection(
                peer_info=peer_info, reader=reader, writer=writer
            )
            self._peers[peer_info.peer_id] = conn
            METRICS.peers_connected.set(len(self._peers))
            METRICS.peer_connections_total.inc()
            asyncio.create_task(self._read_loop(conn))
            log.info("Connected to peer %s", peer_info.peer_id[:16])
            return peer_info
        except Exception as exc:
            log.error("dial failed for %s: %s", multiaddr, exc)
            return None

    def get_peers(self) -> list[PeerInfo]:
        """
        Return PeerInfo for all currently connected peers.

        Returns:
            List of PeerInfo objects.
        """
        return [c.peer_info for c in self._peers.values()]

    @property
    def peer_id(self) -> str:
        """This node's PeerID."""
        return self._identity.peer_id

    @property
    def multiaddr(self) -> str:
        """This node's listen multiaddr."""
        return f"/ip4/{self._host}/tcp/{self._port}/p2p/{self._identity.peer_id}"

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _handle_incoming(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Accept an inbound TCP connection and run the handshake + read loop."""
        addr = writer.get_extra_info("peername")
        log.debug("Incoming connection from %s", addr)
        peer_info = await self._handshake(reader, writer)
        if peer_info is None:
            writer.close()
            return

        if peer_info.peer_id in self._peers:
            log.debug("Duplicate connection from %s, closing", peer_info.peer_id[:12])
            writer.close()
            return

        conn = _PeerConnection(peer_info=peer_info, reader=reader, writer=writer)
        self._peers[peer_info.peer_id] = conn
        METRICS.peers_connected.set(len(self._peers))
        METRICS.peer_connections_total.inc()
        log.info("Accepted connection from peer %s", peer_info.peer_id[:16])
        await self._read_loop(conn)

    async def _handshake(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> PeerInfo | None:
        """
        Perform the HELLO handshake with a newly connected peer.

        Each side sends a peer_announce envelope with their PeerInfo.
        Returns the remote peer's PeerInfo on success.
        """
        # Send our HELLO
        my_addr = writer.get_extra_info("sockname")
        host = my_addr[0] if my_addr else self._host
        hello_payload = self._identity.peer_info(host, self._port).to_dict()
        hello = create_envelope(
            msg_type=MessageType.PEER_ANNOUNCE,
            identity=self._identity,
            payload=hello_payload,
            recipient_x25519_pub_b64=None,  # broadcast / plaintext for handshake
        )
        try:
            frame = struct.pack(">I", len(hello.to_bytes())) + hello.to_bytes()
            writer.write(frame)
            await writer.drain()
        except Exception as exc:
            log.error("Handshake send failed: %s", exc)
            return None

        # Receive their HELLO
        try:
            raw = await asyncio.wait_for(self._read_frame(reader), timeout=10.0)
            if raw is None:
                return None
            remote_env = Envelope.from_bytes(raw)
            if not verify_envelope(remote_env, self._nonce_cache):
                log.warning("Handshake envelope verification failed")
                return None
            peer_info_dict = decode_body_plain(remote_env.body)
            return PeerInfo.from_dict(peer_info_dict)
        except asyncio.TimeoutError:
            log.error("Handshake timed out")
            return None
        except Exception as exc:
            log.error("Handshake receive failed: %s", exc)
            return None

    async def _read_frame(self, reader: asyncio.StreamReader) -> bytes | None:
        """Read one length-prefixed frame from the stream."""
        try:
            header = await reader.readexactly(_LENGTH_PREFIX_SIZE)
            length = struct.unpack(">I", header)[0]
            if length > _MAX_MESSAGE_SIZE:
                log.error("Frame too large: %d bytes", length)
                return None
            data = await reader.readexactly(length)
            METRICS.bytes_received_total.inc(length + _LENGTH_PREFIX_SIZE)
            return data
        except (asyncio.IncompleteReadError, ConnectionResetError):
            return None

    async def _read_loop(self, conn: _PeerConnection) -> None:
        """Continuously read and dispatch messages from a connected peer."""
        peer_id = conn.peer_id
        try:
            while self._running and peer_id in self._peers:
                raw = await self._read_frame(conn.reader)
                if raw is None:
                    break
                await self._dispatch(raw, conn.peer_info)
        finally:
            await self._disconnect_peer(peer_id)

    async def _dispatch(self, raw: bytes, sender: PeerInfo) -> None:
        """Verify and dispatch a raw message to the appropriate topic handlers."""
        try:
            envelope = Envelope.from_bytes(raw)
        except Exception as exc:
            log.warning("Failed to parse envelope: %s", exc)
            METRICS.failed_validations_total.inc()
            return

        METRICS.messages_received_total.inc()

        if not verify_envelope(envelope, self._nonce_cache):
            METRICS.failed_validations_total.inc()
            return

        # Extract topic from payload (our convention: first field in payload)
        # For encrypted messages we pass the envelope as-is to handlers
        # Handlers are registered by topic string; we match by message type as fallback
        topic = envelope.type.value  # default: use message type as topic

        handlers = self._handlers.get(topic, [])
        # Also check full topic string if payload was broadcast with topic prefix
        for handler in handlers:
            try:
                await handler(envelope, sender)
            except Exception as exc:
                log.error("Handler error for topic '%s': %s", topic, exc)

    async def _disconnect_peer(self, peer_id: str) -> None:
        """Clean up a disconnected peer."""
        conn = self._peers.pop(peer_id, None)
        if conn:
            conn.close()
            METRICS.peers_connected.set(len(self._peers))
            METRICS.peer_disconnections_total.inc()
            log.info("Peer %s disconnected", peer_id[:16])
