"""
Federated RAG retrieval orchestrator for AURA.

FederatedRetriever coordinates:
  1. Local ChromaDB retrieval.
  2. P2P broadcast of the query to connected peers.
  3. Encrypted response collection with timeout + quorum.
  4. RRF fusion of local + peer results.
  5. Consensus filtering (tombstones, deduplication).

It also registers handlers on the P2P adapter so this node can SERVICE
incoming federated queries from other peers.

Query protocol
  REQUEST  (→ all peers via adapter.publish):
    type: query_request
    body: {
        "query_id": "<uuid>",
        "question": "<text>",         # encrypted per peer
        "max_results": <int>,
        "auth_sig": "<b64>",          # Auth signature placeholder; ZKP in Security
        "requester_peer_id": "<id>",
        "requester_x25519_pub": "<b64>"
    }

  RESPONSE (→ requester directly via adapter.publish_envelope):
    type: query_response
    body: {
        "query_id": "<uuid>",
        "chunks": [ <chunk>, ... ],   # encrypted for requester
        "node_id": "<peer_id>"
    }
"""

import asyncio
import base64
import json
import uuid
from dataclasses import dataclass, field
from typing import Callable

from backend.config import (
    FEDERATED_LOCAL_FANOUT,
    FEDERATED_MAX_RESPONSES,
    FEDERATED_QUORUM,
    FEDERATED_TIMEOUT,
    FEDERATED_TOP_K,
    RRF_K,
)
from backend.network.libp2p_adapter import AuraP2PAdapter
from backend.network.peer import PeerIdentity, PeerInfo
from backend.network.protocol import (
    Envelope,
    MessageType,
    create_envelope,
    decrypt_body,
    encode_body_plain,
)
from backend.network.metrics import METRICS
from backend.rag.consensus import apply_tombstones, deduplicate, tag_provenance
from backend.rag.prompt import build_prompt
from backend.rag.rrf import assign_chunk_ids, rrf_fuse
from backend.storage.ipfs_integration import compute_cid_v1, is_valid_cid_v1
from backend.utils.hashing import sha256_text
from backend.utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class FederatedResult:
    """
    Result of a federated query containing fused chunks with provenance.

    Attributes:
        chunks: RRF-fused chunk list, sorted by rrf_score descending.
        local_count: Number of chunks from local retrieval.
        peer_count: Number of chunks from remote peers.
        peers_responded: List of peer_ids that responded.
        query_id: Unique ID for this federated query.
        duration_ms: Total time from broadcast to result in milliseconds.
    """

    chunks: list[dict]
    local_count: int
    peer_count: int
    peers_responded: list[str]
    query_id: str
    duration_ms: float

    def build_prompt(self, question: str) -> str:
        """Build a grounded RAG prompt from the fused chunks."""
        return build_prompt(question, self.chunks[:FEDERATED_TOP_K])


# ── Retriever type alias ──────────────────────────────────────────────────────
LocalRetrieverFn = Callable[[str, int, float], list[dict]]


def _default_local_retriever(
    question: str,
    top_k: int,
    threshold: float = 1.0,
) -> list[dict]:
    """Default retriever: uses ChromaDB retrieve()."""
    from backend.rag.retriever import retrieve

    return retrieve(question, top_k=top_k, score_threshold=threshold)


# ── FederatedRetriever ────────────────────────────────────────────────────────


class FederatedRetriever:
    """
    Coordinates federated RAG retrieval across local + P2P peers.

    Usage:
        retriever = FederatedRetriever(identity, adapter)
        result = await retriever.query("What is our Q3 revenue?")
        prompt = result.build_prompt("What is our Q3 revenue?")
    """

    def __init__(
        self,
        identity: PeerIdentity,
        adapter: AuraP2PAdapter,
        local_retriever: LocalRetrieverFn | None = None,
    ) -> None:
        self._identity = identity
        self._adapter = adapter
        self._local_retriever = local_retriever or _default_local_retriever

        # In-flight query state: query_id → asyncio.Queue of peer chunk lists
        self._pending: dict[str, asyncio.Queue] = {}

        # Register handlers for incoming P2P messages
        adapter.subscribe(MessageType.QUERY_REQUEST.value, self._handle_peer_query)
        adapter.subscribe(MessageType.QUERY_RESPONSE.value, self._handle_peer_response)

        log.info("FederatedRetriever ready (peer_id=%s)", identity.peer_id[:16])

    # ── Public API ────────────────────────────────────────────────────────────

    async def query(
        self,
        question: str,
        top_k: int = FEDERATED_TOP_K,
        timeout: float = FEDERATED_TIMEOUT,
    ) -> FederatedResult:
        """
        Execute a federated query: local retrieval + P2P broadcast + RRF.

        Args:
            question: Natural language question.
            top_k: Maximum number of fused chunks to return.
            timeout: Seconds to wait for peer responses.

        Returns:
            FederatedResult with fused chunks and provenance metadata.
        """
        import time

        t0 = time.monotonic()
        query_id = str(uuid.uuid4())

        # ── 1. Local retrieval ─────────────────────────────────────────────
        local_fanout = top_k * FEDERATED_LOCAL_FANOUT
        local_raw = self._local_retriever(question, local_fanout, 1.0)
        local_tagged = tag_provenance(
            assign_chunk_ids(local_raw),
            node_id="local",
        )
        log.info(
            "Federated[%s] local=%d chunks",
            query_id[:8],
            len(local_tagged),
        )

        # ── 2. If no peers, return local only ──────────────────────────────────
        peers = self._adapter.get_peers()
        if not peers:
            local_clean = apply_tombstones(local_tagged)
            fused = rrf_fuse([local_clean], k=RRF_K, top_k=top_k)
            return FederatedResult(
                chunks=fused,
                local_count=len(local_tagged),
                peer_count=0,
                peers_responded=[],
                query_id=query_id,
                duration_ms=round((time.monotonic() - t0) * 1000, 1),
            )

        # ── 3. Broadcast query to all peers ────────────────────────────────
        queue: asyncio.Queue = asyncio.Queue()
        self._pending[query_id] = queue

        try:
            await self._adapter.publish(
                MessageType.QUERY_REQUEST.value,
                {
                    "query_id": query_id,
                    "question": question,
                    "max_results": top_k * 2,
                    "auth_sig": base64.b64encode(
                        self._identity.sign(question.encode())
                    ).decode(),
                    "requester_peer_id": self._identity.peer_id,
                    "requester_x25519_pub": self._identity.x25519_pubkey_b64,
                },
            )

            # ── 4. Collect responses with timeout + quorum ─────────────────
            peer_rankings: list[list[dict]] = []
            peers_responded: list[str] = []
            deadline = time.monotonic() + timeout
            max_collect = min(len(peers), FEDERATED_MAX_RESPONSES)

            for _ in range(max_collect):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    peer_id, chunks = await asyncio.wait_for(
                        queue.get(), timeout=remaining
                    )
                    peer_rankings.append(assign_chunk_ids(chunks))
                    peers_responded.append(peer_id)
                    log.info(
                        "Federated[%s] peer %s → %d chunks",
                        query_id[:8],
                        peer_id[:12],
                        len(chunks),
                    )
                    # Early exit if quorum reached
                    if len(peers_responded) >= FEDERATED_QUORUM:
                        # drain briefly then break
                        break
                except asyncio.TimeoutError:
                    log.info("Federated[%s] timeout waiting for peers", query_id[:8])
                    break

        finally:
            self._pending.pop(query_id, None)

        # ── 5. RRF fusion ──────────────────────────────────────────────────
        all_rankings = [local_tagged] + peer_rankings
        total_peer_chunks = sum(len(r) for r in peer_rankings)

        fused_raw = rrf_fuse(all_rankings, k=RRF_K)
        fused_clean = deduplicate(apply_tombstones(fused_raw))
        fused = fused_clean[:top_k]

        duration = round((time.monotonic() - t0) * 1000, 1)
        log.info(
            "Federated[%s] complete: %d fused chunks from %d peer(s) in %s ms",
            query_id[:8],
            len(fused),
            len(peers_responded),
            duration,
        )

        return FederatedResult(
            chunks=fused,
            local_count=len(local_tagged),
            peer_count=total_peer_chunks,
            peers_responded=peers_responded,
            query_id=query_id,
            duration_ms=duration,
        )

    # ── P2P message handlers ──────────────────────────────────────────────────

    async def _handle_peer_query(self, envelope: Envelope, sender: PeerInfo) -> None:
        """
        Handle an incoming query_request from another node.

        Decrypts the question, runs local retrieval, and sends a query_response
        directly back to the requester.
        """
        # Decrypt body: sender encrypted it with our X25519 pubkey
        try:
            payload = decrypt_body(
                envelope.body,
                self._identity.x25519_private,
                envelope.from_peer.get("x25519_pubkey_b64", ""),
            )
        except Exception as exc:
            log.warning("Failed to decrypt incoming query: %s", exc)
            return

        query_id = payload.get("query_id", "")
        question = payload.get("question", "")
        max_results = int(payload.get("max_results", FEDERATED_TOP_K * 2))
        requester_peer_id = payload.get("requester_peer_id", "")
        requester_x25519_pub = payload.get("requester_x25519_pub", "")

        if not question or not requester_peer_id:
            log.warning("Received malformed query_request from %s", sender.peer_id[:12])
            return

        log.info(
            "Serving federated query %s from %s",
            query_id[:8],
            sender.peer_id[:12],
        )

        # Run local retrieval
        try:
            local_chunks = self._local_retriever(question, max_results, 1.0)
            tagged = tag_provenance(
                assign_chunk_ids(local_chunks),
                node_id=self._identity.peer_id,
            )
            clean = apply_tombstones(tagged)
        except Exception as exc:
            log.error("Local retrieval failed while serving peer query: %s", exc)
            clean = []

        # Build and send response
        response_payload = {
            "query_id": query_id,
            "chunks": clean,
            "node_id": self._identity.peer_id,
        }
        response_envelope = create_envelope(
            msg_type=MessageType.QUERY_RESPONSE,
            identity=self._identity,
            payload=response_payload,
            recipient_x25519_pub_b64=requester_x25519_pub,
        )
        await self._adapter.publish_envelope(response_envelope, requester_peer_id)

    async def _handle_peer_response(self, envelope: Envelope, sender: PeerInfo) -> None:
        """
        Handle an incoming query_response from a peer.

        Decrypts the body and routes the chunks to the pending query's queue.
        """
        try:
            payload = decrypt_body(
                envelope.body,
                self._identity.x25519_private,
                envelope.from_peer.get("x25519_pubkey_b64", ""),
            )
        except Exception as exc:
            log.warning("Failed to decrypt query_response: %s", exc)
            return

        query_id = payload.get("query_id", "")
        raw_chunks = payload.get("chunks", [])
        node_id = payload.get("node_id", sender.peer_id)

        # ── CID integrity check ──────────────────────────────────────────────
        # Reject any chunk whose ipfs_cid doesn't match its text content.
        # This detects tampering or data corruption at rest on peer nodes.
        chunks = []
        for chunk in raw_chunks:
            ipfs_cid = chunk.get("ipfs_cid", "")
            text = chunk.get("text", "")
            if ipfs_cid and is_valid_cid_v1(ipfs_cid):
                # Recompute CID from text bytes and compare
                actual_cid = compute_cid_v1(text.encode("utf-8"))
                if actual_cid != ipfs_cid:
                    log.warning(
                        "CID mismatch from peer %s: expected=%s actual=%s – chunk rejected",
                        node_id[:12],
                        ipfs_cid[:16],
                        actual_cid[:16],
                    )
                    METRICS.failed_validations_total.inc()
                    continue
            chunks.append(chunk)

        queue = self._pending.get(query_id)
        if queue is not None:
            await queue.put((node_id, chunks))
        else:
            log.debug("Received response for unknown/expired query_id %s", query_id[:8])
