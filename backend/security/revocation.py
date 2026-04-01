"""
Document revocation for AURA – Phase 4.

RevocationManager handles:
  1. Local revocation: tombstone a CID, delete its vectors from ChromaDB.
  2. P2P broadcast: publish a signed revocation envelope on
     /aura/revocations/1.0.0 so all peers know to tombstone too.
  3. Incoming revocations: verify signature, tombstone + clean ChromaDB.

Wire format (body of a query_response envelope, plaintext broadcast):
  {
    "cid":        "<sha256-hex>",
    "ipfs_cid":   "<cidv1-string>",
    "revoked_at": <unix-timestamp>,
    "reason":     "<optional string>",
    "peer_id":    "<revoking-peer-id>"
  }
"""
import base64
import json
import time
from typing import TYPE_CHECKING

from backend.network.peer import PeerIdentity, PeerInfo
from backend.network.protocol import (
    Envelope,
    MessageType,
    create_envelope,
    decode_body_plain,
    encode_body_plain,
)
from backend.rag.consensus import add_tombstone, get_tombstones
from backend.utils.logging import get_logger

if TYPE_CHECKING:
    from backend.network.libp2p_adapter import AuraP2PAdapter

log = get_logger(__name__)

REVOCATION_TOPIC = "/aura/revocations/1.0.0"


class RevocationManager:
    """
    Manages document revocation across the AURA mesh.

    On creation, registers a handler on the P2P adapter for the
    /aura/revocations/1.0.0 Gossipsub topic.

    Usage:
        mgr = RevocationManager(identity, adapter)
        await mgr.revoke("sha256hex...", reason="GDPR request")
    """

    def __init__(
        self,
        identity: PeerIdentity,
        adapter: "AuraP2PAdapter",
    ) -> None:
        self._identity = identity
        self._adapter = adapter

        # Subscribe to incoming revocations from peers
        adapter.subscribe(REVOCATION_TOPIC, self._handle_revocation)
        log.info("RevocationManager ready (peer_id=%s)", identity.peer_id[:16])

    # ── Public API ────────────────────────────────────────────────────────────

    async def revoke(
        self,
        cid: str,
        ipfs_cid: str = "",
        reason: str = "",
    ) -> None:
        """
        Revoke a document locally and broadcast to all peers.

        Steps:
          1. Tombstone the CID in the local consensus store.
          2. Delete matching vectors from ChromaDB.
          3. Broadcast signed revocation envelope to all peers.

        Args:
            cid: SHA-256 content ID of the document to revoke.
            ipfs_cid: IPFS CIDv1 of the document (optional, for verification).
            reason: Human-readable revocation reason.
        """
        # Local tombstone
        add_tombstone(cid)
        deleted = self._delete_from_chroma(cid)
        log.info(
            "Revoked CID %s locally (%d chunks deleted)", cid[:12], deleted
        )

        # Broadcast to peers
        if self._adapter.get_peers():
            payload = {
                "cid": cid,
                "ipfs_cid": ipfs_cid,
                "revoked_at": time.time(),
                "reason": reason,
                "peer_id": self._identity.peer_id,
            }
            # Use plaintext body for broadcast (no single recipient)
            envelope = Envelope(
                version="1.0",
                type=MessageType.QUERY_RESPONSE,  # reuse existing type for wire compat
                from_peer={
                    "peer_id": self._identity.peer_id,
                    "ed25519_pubkey_b64": self._identity.ed25519_pubkey_b64,
                    "x25519_pubkey_b64": self._identity.x25519_pubkey_b64,
                },
                nonce=base64.b64encode(__import__("os").urandom(16)).decode(),
                ts=time.time(),
                body=encode_body_plain(payload),
                sig="",
            )
            # Sign the envelope
            sig = self._identity.sign(envelope._signable())
            envelope.sig = base64.b64encode(sig).decode()

            # Send to all connected peers directly
            for peer in self._adapter.get_peers():
                await self._adapter.publish_envelope(envelope, peer.peer_id)

            log.info(
                "Revocation broadcast for CID %s to %d peer(s)",
                cid[:12],
                len(self._adapter.get_peers()),
            )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _delete_from_chroma(self, cid: str) -> int:
        """
        Delete all ChromaDB chunks whose 'cid' metadata matches.

        Returns:
            Number of chunks deleted.
        """
        try:
            from backend.database.chroma import get_collection
            col = get_collection()
            results = col.get(where={"cid": cid}, include=["metadatas"])
            ids = results.get("ids", [])
            if ids:
                col.delete(ids=ids)
                log.info("Deleted %d ChromaDB chunks for CID %s", len(ids), cid[:12])
            return len(ids)
        except Exception as exc:
            log.error("ChromaDB deletion failed for CID %s: %s", cid[:12], exc)
            return 0

    async def _handle_revocation(
        self, envelope: Envelope, sender: PeerInfo
    ) -> None:
        """
        Handle an incoming revocation broadcast from a peer.

        Verifies the envelope signature, tombstones the CID locally,
        and removes related vectors from ChromaDB.
        """
        # Verify envelope signature
        from backend.network.protocol import verify_envelope
        nonce_cache: set[str] = set()
        if not verify_envelope(envelope, nonce_cache):
            log.warning(
                "Rejected revocation from peer %s: invalid envelope",
                sender.peer_id[:12],
            )
            return

        # Decode the plaintext body
        try:
            payload = decode_body_plain(envelope.body)
        except Exception as exc:
            log.warning("Failed to decode revocation body: %s", exc)
            return

        cid = payload.get("cid", "")
        revoker = payload.get("peer_id", sender.peer_id)
        reason = payload.get("reason", "")

        if not cid:
            log.warning("Received revocation with no CID from %s", sender.peer_id[:12])
            return

        # Already tombstoned?
        if cid in get_tombstones():
            log.debug("CID %s already tombstoned, ignoring duplicate revocation", cid[:12])
            return

        add_tombstone(cid)
        deleted = self._delete_from_chroma(cid)
        log.info(
            "Applied peer revocation: CID %s from %s (reason=%r, %d chunks deleted)",
            cid[:12],
            revoker[:12],
            reason,
            deleted,
        )
