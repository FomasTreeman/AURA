"""
Signed model manifest for AURA answer determinism.

Every AURA node gossips a signed manifest describing its active LLM:
  - Model name and Ollama tag
  - SHA-256 of the model blob (if available via Ollama API)
  - Node's peer_id and Ed25519 signature
  - Timestamp

When a node receives a query, it can check the requester's manifest
against its own. If models differ significantly, the node can fall back
to a designated "heavy-lifter" node (Phase 5+ routing logic).

Gossip topic: /aura/model_manifest/1.0.0
"""
import base64
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from backend.config import OLLAMA_BASE_URL, OLLAMA_MODEL
from backend.network.peer import PeerIdentity, verify_signature
from backend.utils.logging import get_logger

log = get_logger(__name__)

_MANIFEST_VERSION = 1
MODEL_MANIFEST_TOPIC = "/aura/model_manifest/1.0.0"


@dataclass
class ModelManifest:
    """
    Signed manifest describing a node's active LLM.

    Attributes:
        version: Manifest schema version.
        peer_id: The signing node's peer_id.
        model_name: Human-readable model name (e.g. 'llama3.2:3b').
        ollama_tag: Exact Ollama tag pulled.
        model_sha256: SHA-256 of the model blob, or empty if unavailable.
        created_at: Unix timestamp of manifest creation.
        ed25519_pubkey_b64: Signer's public key for verification.
        signature_b64: Ed25519 signature over canonical payload bytes.
    """
    version: int
    peer_id: str
    model_name: str
    ollama_tag: str
    model_sha256: str
    created_at: float
    ed25519_pubkey_b64: str
    signature_b64: str

    def to_signable_bytes(self) -> bytes:
        """Canonical serialisation for signing (excludes signature_b64)."""
        return json.dumps(
            {
                "version": self.version,
                "peer_id": self.peer_id,
                "model_name": self.model_name,
                "ollama_tag": self.ollama_tag,
                "model_sha256": self.model_sha256,
                "created_at": f"{self.created_at:.6f}",
                "ed25519_pubkey_b64": self.ed25519_pubkey_b64,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "peer_id": self.peer_id,
            "model_name": self.model_name,
            "ollama_tag": self.ollama_tag,
            "model_sha256": self.model_sha256,
            "created_at": self.created_at,
            "ed25519_pubkey_b64": self.ed25519_pubkey_b64,
            "signature_b64": self.signature_b64,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ModelManifest":
        return cls(
            version=data["version"],
            peer_id=data["peer_id"],
            model_name=data["model_name"],
            ollama_tag=data["ollama_tag"],
            model_sha256=data.get("model_sha256", ""),
            created_at=float(data["created_at"]),
            ed25519_pubkey_b64=data["ed25519_pubkey_b64"],
            signature_b64=data["signature_b64"],
        )

    def is_compatible_with(self, other: "ModelManifest") -> bool:
        """
        Check if this manifest's model is compatible with another.
        Two manifests are compatible if they reference the same Ollama tag.
        """
        return self.ollama_tag == other.ollama_tag


async def _fetch_model_sha256(model_tag: str) -> str:
    """
    Attempt to fetch the model blob SHA-256 from the Ollama API.

    Returns:
        SHA-256 hex string, or empty string if unavailable.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{OLLAMA_BASE_URL}/api/show",
                json={"name": model_tag},
            )
            resp.raise_for_status()
            data = resp.json()
            # Ollama returns a digest in the model info
            digest = data.get("digest", "")
            if digest.startswith("sha256:"):
                return digest[7:]
            return digest
    except Exception:
        return ""


async def create_manifest(
    identity: PeerIdentity,
    model_name: str = OLLAMA_MODEL,
    ollama_tag: str | None = None,
) -> ModelManifest:
    """
    Create a signed ModelManifest for this node's current LLM.

    Args:
        identity: The node's PeerIdentity (signing key).
        model_name: Human-readable model name.
        ollama_tag: Exact Ollama tag. Defaults to model_name.

    Returns:
        Signed ModelManifest.
    """
    tag = ollama_tag or model_name
    model_sha256 = await _fetch_model_sha256(tag)

    manifest = ModelManifest(
        version=_MANIFEST_VERSION,
        peer_id=identity.peer_id,
        model_name=model_name,
        ollama_tag=tag,
        model_sha256=model_sha256,
        created_at=time.time(),
        ed25519_pubkey_b64=identity.ed25519_pubkey_b64,
        signature_b64="",  # placeholder
    )
    sig = identity.sign(manifest.to_signable_bytes())
    manifest.signature_b64 = base64.b64encode(sig).decode()
    log.info(
        "Created model manifest: tag=%s sha256=%s...",
        tag,
        model_sha256[:12] if model_sha256 else "n/a",
    )
    return manifest


def verify_manifest(manifest: ModelManifest) -> bool:
    """
    Verify a ModelManifest's Ed25519 signature.

    Args:
        manifest: The manifest to verify.

    Returns:
        True if the signature is valid.
    """
    valid = verify_signature(
        manifest.signature_b64,
        manifest.to_signable_bytes(),
        manifest.ed25519_pubkey_b64,
    )
    if not valid:
        log.warning(
            "Invalid manifest signature from peer %s", manifest.peer_id[:16]
        )
    return valid


def store_manifest(manifest: ModelManifest, path: Path) -> None:
    """Persist a manifest to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), indent=2))


def load_manifest(path: Path) -> ModelManifest | None:
    """Load a manifest from a JSON file, returning None if missing."""
    if not path.exists():
        return None
    try:
        return ModelManifest.from_dict(json.loads(path.read_text()))
    except Exception as exc:
        log.warning("Failed to load manifest from %s: %s", path, exc)
        return None
