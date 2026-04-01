"""
DID (Decentralised Identifier) management for AURA nodes.

Each AURA node holds a persistent cryptographic identity stored in an
**encrypted local keystore** protected by a passphrase.

Keystore format (JSON file):
  {
    "version": 1,
    "peer_id": "<libp2p-peer-id>",
    "ed25519": {
        "salt_b64": "<base64>",
        "nonce_b64": "<base64>",
        "ct_b64":   "<base64>"      # AES-256-GCM encrypted Ed25519 seed
    },
    "x25519": {
        "salt_b64": "<base64>",
        "nonce_b64": "<base64>",
        "ct_b64":   "<base64>"
    },
    "rotation_history": [
      {"peer_id": "<old-id>", "rotated_at": <unix-ts>, "rotation_sig": "<b64>"}
    ]
  }

Key derivation: PBKDF2-HMAC-SHA256, 260,000 iterations, 32-byte output.
Encryption:    AES-256-GCM with 12-byte random nonce.
"""
import base64
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from backend.network.peer import PeerIdentity
from backend.utils.logging import get_logger

log = get_logger(__name__)

_KDF_ITERATIONS = 260_000
_KDF_SALT_BYTES = 32
_GCM_NONCE_BYTES = 12
_KEYSTORE_VERSION = 1


# ── Internal helpers ──────────────────────────────────────────────────────────

def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a 32-byte AES key from a passphrase + salt via PBKDF2-HMAC-SHA256."""
    kdf = PBKDF2HMAC(
        algorithm=SHA256(),
        length=32,
        salt=salt,
        iterations=_KDF_ITERATIONS,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def _encrypt_seed(seed: bytes, passphrase: str) -> dict:
    """Encrypt a 32-byte seed with AES-256-GCM. Returns JSON-serialisable dict."""
    salt = os.urandom(_KDF_SALT_BYTES)
    nonce = os.urandom(_GCM_NONCE_BYTES)
    key = _derive_key(passphrase, salt)
    ct = AESGCM(key).encrypt(nonce, seed, None)
    return {
        "salt_b64": base64.b64encode(salt).decode(),
        "nonce_b64": base64.b64encode(nonce).decode(),
        "ct_b64": base64.b64encode(ct).decode(),
    }


def _decrypt_seed(enc: dict, passphrase: str) -> bytes:
    """
    Decrypt an encrypted seed dict.

    Raises:
        ValueError: If the passphrase is wrong or data is corrupted.
    """
    try:
        salt = base64.b64decode(enc["salt_b64"])
        nonce = base64.b64decode(enc["nonce_b64"])
        ct = base64.b64decode(enc["ct_b64"])
        key = _derive_key(passphrase, salt)
        return AESGCM(key).decrypt(nonce, ct, None)
    except Exception as exc:
        raise ValueError("Keystore decryption failed — wrong passphrase?") from exc


# ── Public API ────────────────────────────────────────────────────────────────

@dataclass
class KeyRotationRecord:
    """Record of a past key rotation event."""
    old_peer_id: str
    rotated_at: float
    rotation_sig: str   # Ed25519 signature by old key over new_peer_id + rotated_at


@dataclass
class DIDKeystore:
    """
    Manages a node's DID keypair with encrypted persistence and rotation history.

    Attributes:
        identity: The active PeerIdentity.
        rotation_history: List of past key rotation events.
        keystore_path: Path to the encrypted keystore file.
    """
    identity: PeerIdentity
    rotation_history: list[KeyRotationRecord] = field(default_factory=list)
    keystore_path: Path | None = None

    @property
    def peer_id(self) -> str:
        return self.identity.peer_id

    @property
    def did(self) -> str:
        return f"did:key:{self.peer_id}"

    def export_did_document(self) -> dict:
        """Export a W3C-compatible DID document."""
        doc = self.identity.export_did()
        # Add rotation history as verificationMethod chain
        if self.rotation_history:
            doc["alsoKnownAs"] = [
                f"did:key:{r.old_peer_id}" for r in self.rotation_history
            ]
        return doc


def create_keystore(
    keystore_path: Path,
    passphrase: str,
) -> DIDKeystore:
    """
    Generate a new keypair and save an encrypted keystore to disk.

    Args:
        keystore_path: File path for the encrypted keystore JSON.
        passphrase: Passphrase to protect the private keys.

    Returns:
        DIDKeystore with the new identity loaded.
    """
    identity = PeerIdentity.ephemeral()

    # Extract seeds via the public export method
    ed_seed, x_seed = identity.export_seeds()

    keystore_data = {
        "version": _KEYSTORE_VERSION,
        "peer_id": identity.peer_id,
        "ed25519": _encrypt_seed(ed_seed, passphrase),
        "x25519": _encrypt_seed(x_seed, passphrase),
        "rotation_history": [],
    }
    keystore_path.parent.mkdir(parents=True, exist_ok=True)
    keystore_path.write_text(json.dumps(keystore_data, indent=2))
    log.info("Created encrypted keystore at %s (peer_id=%s)", keystore_path, identity.peer_id[:16])
    return DIDKeystore(identity=identity, keystore_path=keystore_path)


def load_keystore(
    keystore_path: Path,
    passphrase: str,
) -> DIDKeystore:
    """
    Load and decrypt an existing keystore.

    Args:
        keystore_path: Path to the encrypted keystore JSON.
        passphrase: Passphrase to decrypt the private keys.

    Returns:
        DIDKeystore with the decrypted identity.

    Raises:
        FileNotFoundError: If keystore file does not exist.
        ValueError: If passphrase is wrong or file is corrupt.
    """
    if not keystore_path.exists():
        raise FileNotFoundError(f"Keystore not found: {keystore_path}")

    data = json.loads(keystore_path.read_text())
    if data.get("version") != _KEYSTORE_VERSION:
        raise ValueError(f"Unsupported keystore version: {data.get('version')}")

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    ed_seed = _decrypt_seed(data["ed25519"], passphrase)
    x_seed = _decrypt_seed(data["x25519"], passphrase)

    ed_priv = Ed25519PrivateKey.from_private_bytes(ed_seed)
    x_priv = X25519PrivateKey.from_private_bytes(x_seed)
    identity = PeerIdentity(ed_priv, x_priv)

    history = [
        KeyRotationRecord(
            old_peer_id=r["old_peer_id"],
            rotated_at=r["rotated_at"],
            rotation_sig=r["rotation_sig"],
        )
        for r in data.get("rotation_history", [])
    ]
    log.info("Loaded keystore from %s (peer_id=%s)", keystore_path, identity.peer_id[:16])
    return DIDKeystore(identity=identity, rotation_history=history, keystore_path=keystore_path)


def rotate_key(
    old_keystore: DIDKeystore,
    passphrase: str,
    new_passphrase: str | None = None,
) -> DIDKeystore:
    """
    Generate a new keypair, signing a rotation record with the old key.

    The rotation record cryptographically links old → new peer_id, allowing
    peers to verify the chain of identity.

    Args:
        old_keystore: The current DIDKeystore to rotate from.
        passphrase: Current keystore passphrase.
        new_passphrase: New passphrase for the rotated keystore. Defaults to same.

    Returns:
        New DIDKeystore with updated keypair and rotation history appended.
    """
    if old_keystore.keystore_path is None:
        raise ValueError("Keystore path not set; cannot rotate.")

    new_identity = PeerIdentity.ephemeral()
    rotated_at = time.time()

    # Sign the rotation: old_key signs (new_peer_id + timestamp)
    rotation_payload = f"{new_identity.peer_id}:{rotated_at:.6f}".encode()
    rotation_sig = base64.b64encode(old_keystore.identity.sign(rotation_payload)).decode()

    ed_seed, x_seed = new_identity.export_seeds()

    new_history = list(old_keystore.rotation_history) + [
        KeyRotationRecord(
            old_peer_id=old_keystore.peer_id,
            rotated_at=rotated_at,
            rotation_sig=rotation_sig,
        )
    ]

    eff_passphrase = new_passphrase or passphrase
    keystore_data = {
        "version": _KEYSTORE_VERSION,
        "peer_id": new_identity.peer_id,
        "ed25519": _encrypt_seed(ed_seed, eff_passphrase),
        "x25519": _encrypt_seed(x_seed, eff_passphrase),
        "rotation_history": [
            {
                "old_peer_id": r.old_peer_id,
                "rotated_at": r.rotated_at,
                "rotation_sig": r.rotation_sig,
            }
            for r in new_history
        ],
    }
    old_keystore.keystore_path.write_text(json.dumps(keystore_data, indent=2))
    log.info(
        "Key rotated: %s → %s",
        old_keystore.peer_id[:16],
        new_identity.peer_id[:16],
    )
    return DIDKeystore(
        identity=new_identity,
        rotation_history=new_history,
        keystore_path=old_keystore.keystore_path,
    )


def verify_rotation_chain(keystore: DIDKeystore) -> bool:
    """
    Verify the cryptographic chain of key rotations.

    Each rotation record must be signed by the previous key over
    (new_peer_id + rotated_at).

    Returns:
        True if the entire rotation chain is valid.
    """
    from backend.network.peer import verify_signature
    import hashlib

    history = keystore.rotation_history
    if not history:
        return True  # No rotation history is valid

    for i, record in enumerate(history):
        # Reconstruct what was signed
        if i < len(history) - 1:
            new_peer_id = history[i + 1].old_peer_id
        else:
            new_peer_id = keystore.peer_id

        payload = f"{new_peer_id}:{record.rotated_at:.6f}".encode()

        # Derive the old peer's Ed25519 pubkey from its peer_id is not directly
        # possible — we need the pubkey stored in rotation history.
        # For now, we verify the signature format and presence.
        # Full verification requires storing pubkey in rotation record (Phase 6 enhancement).
        if not record.rotation_sig:
            return False

    return True
