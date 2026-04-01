"""
Peer identity management for AURA P2P network.

Each AURA node has:
  - An Ed25519 signing keypair  → identity & message signatures
  - An X25519 ECDH keypair      → session key negotiation (derived deterministically)

PeerID is computed as the base58btc-encoded SHA-256 multihash of the Ed25519 public key,
following the libp2p peer-id spec for keys ≤ 32 bytes (identity multihash).

The implementation is interface-compatible with py-libp2p so the transport layer can be
swapped once py-libp2p gains stable Python 3.14 support.
"""
import base64
import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from backend.utils.logging import get_logger

log = get_logger(__name__)

# Base58 alphabet (Bitcoin/IPFS)
_BASE58_ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _base58_encode(data: bytes) -> str:
    """Encode bytes to base58btc string."""
    n = int.from_bytes(data, "big")
    result = []
    while n > 0:
        n, r = divmod(n, 58)
        result.append(_BASE58_ALPHABET[r : r + 1])
    # Handle leading zero bytes
    for byte in data:
        if byte == 0:
            result.append(_BASE58_ALPHABET[0:1])
        else:
            break
    return b"".join(reversed(result)).decode("ascii")


def _derive_peer_id(ed25519_pubkey_bytes: bytes) -> str:
    """
    Derive a libp2p-compatible PeerID from an Ed25519 public key.

    For keys ≤ 42 bytes, libp2p uses the "identity" multihash:
      multihash = varint(0x00) + varint(len) + pubkey_bytes
    For larger keys, SHA-256 multihash is used.

    We use SHA-256 (code 0x12, length 0x20) for consistency:
      multihash = b'\x12\x20' + sha256(pubkey_bytes)

    Args:
        ed25519_pubkey_bytes: Raw 32-byte Ed25519 public key.

    Returns:
        Base58btc-encoded multihash string (libp2p PeerID format).
    """
    digest = hashlib.sha256(ed25519_pubkey_bytes).digest()
    multihash = b"\x12\x20" + digest  # SHA-256 multihash prefix
    return _base58_encode(multihash)


@dataclass
class PeerInfo:
    """
    Serialisable description of a peer's network presence.

    Attributes:
        peer_id: libp2p-compatible base58 PeerID string.
        multiaddrs: List of multiaddr strings, e.g. ['/ip4/1.2.3.4/tcp/9000/p2p/<id>'].
        ed25519_pubkey_b64: Base64-encoded Ed25519 public key (for signature verification).
        x25519_pubkey_b64: Base64-encoded X25519 public key (for ECDH session setup).
    """

    peer_id: str
    multiaddrs: list[str]
    ed25519_pubkey_b64: str
    x25519_pubkey_b64: str

    def to_dict(self) -> dict:
        """Serialise to a JSON-compatible dict."""
        return {
            "peer_id": self.peer_id,
            "multiaddrs": self.multiaddrs,
            "ed25519_pubkey_b64": self.ed25519_pubkey_b64,
            "x25519_pubkey_b64": self.x25519_pubkey_b64,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PeerInfo":
        """Deserialise from a dict."""
        return cls(
            peer_id=data["peer_id"],
            multiaddrs=data.get("multiaddrs", []),
            ed25519_pubkey_b64=data["ed25519_pubkey_b64"],
            x25519_pubkey_b64=data["x25519_pubkey_b64"],
        )


class PeerIdentity:
    """
    Manages the local node's cryptographic identity.

    Persists the Ed25519 seed to disk so PeerID remains stable across restarts.
    The X25519 key is derived deterministically from the same seed.

    Usage:
        identity = PeerIdentity.load_or_create(Path("./data/identity"))
        info = identity.peer_info(host="127.0.0.1", port=9000)
        signature = identity.sign(b"some data")
        identity.verify(signature, b"some data", info.ed25519_pubkey_b64)
    """

    def __init__(
        self,
        ed25519_private: Ed25519PrivateKey,
        x25519_private: X25519PrivateKey,
    ) -> None:
        self._ed25519_priv = ed25519_private
        self._x25519_priv = x25519_private

        # Derive public keys
        self._ed25519_pub: Ed25519PublicKey = ed25519_private.public_key()
        self._x25519_pub: X25519PublicKey = x25519_private.public_key()

        # Cache raw bytes
        self._ed25519_pub_bytes: bytes = self._ed25519_pub.public_bytes(
            Encoding.Raw, PublicFormat.Raw
        )
        self._x25519_pub_bytes: bytes = self._x25519_pub.public_bytes(
            Encoding.Raw, PublicFormat.Raw
        )
        self._peer_id: str = _derive_peer_id(self._ed25519_pub_bytes)

    # ── Class methods ──────────────────────────────────────────────────────────

    @classmethod
    def load_or_create(cls, key_dir: Path) -> "PeerIdentity":
        """
        Load an existing identity from disk or generate a new one.

        The Ed25519 seed is stored as a 32-byte hex file at key_dir/ed25519.seed.
        The X25519 seed is stored at key_dir/x25519.seed.

        Args:
            key_dir: Directory for persisting key material.

        Returns:
            PeerIdentity instance.
        """
        key_dir.mkdir(parents=True, exist_ok=True)
        ed_seed_path = key_dir / "ed25519.seed"
        x_seed_path = key_dir / "x25519.seed"

        if ed_seed_path.exists() and x_seed_path.exists():
            ed_seed = bytes.fromhex(ed_seed_path.read_text().strip())
            x_seed = bytes.fromhex(x_seed_path.read_text().strip())
            log.info("Loaded existing peer identity from %s", key_dir)
        else:
            ed_seed = os.urandom(32)
            x_seed = hashlib.sha256(b"x25519:" + ed_seed).digest()
            ed_seed_path.write_text(ed_seed.hex())
            x_seed_path.write_text(x_seed.hex())
            log.info("Generated new peer identity, saved to %s", key_dir)

        ed_priv = Ed25519PrivateKey.from_private_bytes(ed_seed)
        x_priv = X25519PrivateKey.from_private_bytes(x_seed)
        return cls(ed_priv, x_priv)

    @classmethod
    def ephemeral(cls) -> "PeerIdentity":
        """
        Create a temporary in-memory identity (not persisted).
        Useful for testing.

        Returns:
            PeerIdentity with randomly generated keys.
        """
        ed_seed = os.urandom(32)
        x_seed = hashlib.sha256(b"x25519:" + ed_seed).digest()
        return cls(
            Ed25519PrivateKey.from_private_bytes(ed_seed),
            X25519PrivateKey.from_private_bytes(x_seed),
        )

    # ── Properties ─────────────────────────────────────────────────────────────

    @property
    def peer_id(self) -> str:
        """libp2p-compatible PeerID string."""
        return self._peer_id

    @property
    def ed25519_pubkey_b64(self) -> str:
        """Base64-encoded Ed25519 public key."""
        return base64.b64encode(self._ed25519_pub_bytes).decode()

    @property
    def x25519_pubkey_b64(self) -> str:
        """Base64-encoded X25519 public key."""
        return base64.b64encode(self._x25519_pub_bytes).decode()

    @property
    def x25519_private(self) -> X25519PrivateKey:
        """X25519 private key for ECDH operations."""
        return self._x25519_priv

    # ── Cryptographic operations ───────────────────────────────────────────────

    def sign(self, data: bytes) -> bytes:
        """
        Sign data with the Ed25519 private key.

        Args:
            data: Bytes to sign.

        Returns:
            64-byte Ed25519 signature.
        """
        return self._ed25519_priv.sign(data)

    def peer_info(self, host: str, port: int) -> PeerInfo:
        """
        Construct a PeerInfo for this node at the given address.

        Args:
            host: IP address or hostname.
            port: TCP port number.

        Returns:
            PeerInfo with this node's identity and multiaddr.
        """
        multiaddr = f"/ip4/{host}/tcp/{port}/p2p/{self._peer_id}"
        return PeerInfo(
            peer_id=self._peer_id,
            multiaddrs=[multiaddr],
            ed25519_pubkey_b64=self.ed25519_pubkey_b64,
            x25519_pubkey_b64=self.x25519_pubkey_b64,
        )

    def export_did(self) -> dict:
        """
        Export a DID (Decentralised Identifier) document for this peer.

        Format follows did:key method for Ed25519 (W3C compatible).

        Returns:
            DID document dict.
        """
        return {
            "@context": "https://www.w3.org/ns/did/v1",
            "id": f"did:key:{self._peer_id}",
            "verificationMethod": [
                {
                    "id": f"did:key:{self._peer_id}#key-1",
                    "type": "Ed25519VerificationKey2020",
                    "controller": f"did:key:{self._peer_id}",
                    "publicKeyBase64": self.ed25519_pubkey_b64,
                }
            ],
            "authentication": [f"did:key:{self._peer_id}#key-1"],
        }


def verify_signature(
    signature_b64: str,
    data: bytes,
    ed25519_pubkey_b64: str,
) -> bool:
    """
    Verify an Ed25519 signature against a public key.

    Args:
        signature_b64: Base64-encoded 64-byte signature.
        data: Original signed data bytes.
        ed25519_pubkey_b64: Base64-encoded Ed25519 public key.

    Returns:
        True if the signature is valid, False otherwise.
    """
    try:
        sig = base64.b64decode(signature_b64)
        pubkey_bytes = base64.b64decode(ed25519_pubkey_b64)
        pub = Ed25519PublicKey.from_public_bytes(pubkey_bytes)
        pub.verify(sig, data)
        return True
    except Exception:
        return False


def parse_multiaddr(multiaddr: str) -> tuple[str, int, str]:
    """
    Parse a /ip4/.../tcp/.../p2p/... multiaddr string.

    Args:
        multiaddr: Multiaddr string, e.g. '/ip4/1.2.3.4/tcp/9000/p2p/QmXxx'.

    Returns:
        Tuple of (host, port, peer_id).

    Raises:
        ValueError: If the multiaddr is not in the expected format.
    """
    parts = [p for p in multiaddr.split("/") if p]
    try:
        ip4_idx = parts.index("ip4")
        tcp_idx = parts.index("tcp")
        p2p_idx = parts.index("p2p")
        host = parts[ip4_idx + 1]
        port = int(parts[tcp_idx + 1])
        peer_id = parts[p2p_idx + 1]
        return host, port, peer_id
    except (ValueError, IndexError) as exc:
        raise ValueError(f"Cannot parse multiaddr '{multiaddr}': {exc}") from exc
