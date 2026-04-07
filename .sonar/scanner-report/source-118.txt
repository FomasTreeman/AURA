"""
Node orchestration module.
Spawns and manages ephemeral AURA peer containers via the Docker SDK.
Each spawned node auto-registers with the rendezvous registry on Node 1 and
joins the P2P mesh within one heartbeat cycle (~30s).
"""
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import docker
import docker.errors

from backend.utils.logging import get_logger

log = get_logger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
# Image to use for spawned nodes — tag it in docker-compose with `image: aura-backend:latest`
NODE_IMAGE = "aura-backend:latest"
# Docker network shared by all compose services
DOCKER_NETWORK = "aura-network"
# Host port ranges (above the 3 static nodes that use 8000-8003 / 9000-9003)
_API_PORT_START = 8010
_P2P_PORT_START = 9010
# Max simultaneous spawned nodes (safety cap)
NODE_MAX_COUNT = 10


# ── State ─────────────────────────────────────────────────────────────────────

@dataclass
class SpawnedNode:
    node_id: str
    container_id: str
    container_name: str
    api_port: int
    p2p_port: int
    spawned_at: float = field(default_factory=time.time)
    status: str = "running"


_nodes: dict[str, SpawnedNode] = {}
_api_port_counter = _API_PORT_START
_p2p_port_counter = _P2P_PORT_START


def _docker_client() -> docker.DockerClient:
    return docker.from_env()


# ── Public API ────────────────────────────────────────────────────────────────

def spawn_nodes(count: int = 1, rendezvous_url: str = "http://backend:8000") -> list[SpawnedNode]:
    """
    Spawn `count` new AURA peer containers.

    Each container:
    - Gets unique host ports for its API and P2P listeners
    - Sets RENDEZVOUS_URL so it auto-discovers and dials all live peers
    - Joins the shared aura-network Docker bridge
    """
    global _api_port_counter, _p2p_port_counter

    if len(_nodes) + count > NODE_MAX_COUNT:
        raise ValueError(
            f"Cannot spawn {count} nodes: would exceed NODE_MAX_COUNT={NODE_MAX_COUNT}. "
            f"Currently running: {len(_nodes)}."
        )

    client = _docker_client()
    spawned: list[SpawnedNode] = []

    for _ in range(count):
        node_id = str(uuid.uuid4())[:8]
        container_name = f"aura-node-{node_id}"
        api_port = _api_port_counter
        p2p_port = _p2p_port_counter
        _api_port_counter += 1
        _p2p_port_counter += 1

        try:
            container = client.containers.run(
                image=NODE_IMAGE,
                name=container_name,
                detach=True,
                # Map container's fixed ports (8000/9000) to unique host ports
                ports={
                    "8000/tcp": api_port,
                    "9000/tcp": p2p_port,
                },
                environment={
                    "OLLAMA_BASE_URL": "http://host.docker.internal:11434",
                    "P2P_HOST": "0.0.0.0",
                    "P2P_PORT": "9000",
                    # Advertise the container name so peers on the same Docker network can dial it
                    "P2P_ADVERTISE_HOST": container_name,
                    "RENDEZVOUS_URL": rendezvous_url,
                    "P2P_MDNS_ENABLED": "false",
                    # Unique identity dir per container (ephemeral, no volume mount needed)
                    "P2P_KEY_DIR": f"/tmp/identity-{node_id}",
                },
                network=DOCKER_NETWORK,
                remove=False,
            )

            cid = container.id or getattr(container, "short_id", None)
            if not cid:
                container.remove(force=True)
                raise RuntimeError("Docker returned a container with no ID")

            node = SpawnedNode(
                node_id=node_id,
                container_id=cid,
                container_name=container_name,
                api_port=api_port,
                p2p_port=p2p_port,
            )
            _nodes[node_id] = node
            spawned.append(node)
            log.info("Spawned node %s → container %s (API :%d P2P :%d)", node_id, cid[:12], api_port, p2p_port)

        except Exception:
            # Roll back port counters on failure so we don't leave gaps
            _api_port_counter -= 1
            _p2p_port_counter -= 1
            raise

    return spawned


def list_nodes() -> list[SpawnedNode]:
    """Return all spawned nodes, syncing their status from Docker."""
    if not _nodes:
        return []

    try:
        client = _docker_client()
        for node in list(_nodes.values()):
            try:
                container = client.containers.get(node.container_id)
                node.status = container.status  # "running", "exited", "paused", etc.
            except docker.errors.NotFound:
                node.status = "removed"
    except Exception as exc:
        log.warning("Could not sync container statuses: %s", exc)

    return list(_nodes.values())


def stop_node(node_id: str) -> None:
    """Stop and remove a spawned container."""
    node = _nodes.get(node_id)
    if node is None:
        raise KeyError(f"No spawned node with id '{node_id}'")

    try:
        client = _docker_client()
        container = client.containers.get(node.container_id)
        container.stop(timeout=10)
        container.remove()
        log.info("Stopped and removed node %s (container %s)", node_id, node.container_id[:12])
    except docker.errors.NotFound:
        log.warning("Container for node %s already gone", node_id)
    except Exception as exc:
        log.error("Error stopping node %s: %s", node_id, exc)
        raise
    finally:
        del _nodes[node_id]


def stop_all_nodes() -> None:
    """Stop all spawned nodes — called during backend shutdown."""
    for node_id in list(_nodes.keys()):
        try:
            stop_node(node_id)
        except Exception as exc:
            log.warning("Failed to stop node %s during shutdown: %s", node_id, exc)
