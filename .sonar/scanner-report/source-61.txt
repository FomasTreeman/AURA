"""
Unit tests for backend.orchestration.nodes.
Docker SDK calls are fully mocked — no Docker daemon required.
"""
import pytest
from unittest.mock import MagicMock, patch, call

import backend.orchestration.nodes as orch
from backend.orchestration.nodes import (
    SpawnedNode,
    spawn_nodes,
    list_nodes,
    stop_node,
    stop_all_nodes,
    NODE_MAX_COUNT,
    _nodes,
)


# ── Helpers / fixtures ────────────────────────────────────────────────────────

def _make_mock_container(container_id="abc123def456abc123def456"):
    container = MagicMock()
    container.id = container_id
    container.short_id = container_id[:12]
    container.status = "running"
    return container


@pytest.fixture(autouse=True)
def clean_nodes():
    """Reset the in-memory node registry and port counters before each test."""
    _nodes.clear()
    orch._api_port_counter = orch._API_PORT_START
    orch._p2p_port_counter = orch._P2P_PORT_START
    yield
    _nodes.clear()
    orch._api_port_counter = orch._API_PORT_START
    orch._p2p_port_counter = orch._P2P_PORT_START


@pytest.fixture
def mock_docker():
    """Patch _docker_client() to return a mock Docker client."""
    container = _make_mock_container()
    client = MagicMock()
    client.containers.run.return_value = container
    client.containers.get.return_value = container

    with patch("backend.orchestration.nodes._docker_client", return_value=client):
        yield client, container


# ── spawn_nodes ───────────────────────────────────────────────────────────────

class TestSpawnNodes:
    def test_spawns_one_node_by_default(self, mock_docker):
        result = spawn_nodes(1)
        assert len(result) == 1

    def test_spawns_multiple_nodes(self, mock_docker):
        result = spawn_nodes(3)
        assert len(result) == 3

    def test_returns_spawned_node_objects(self, mock_docker):
        result = spawn_nodes(1)
        assert isinstance(result[0], SpawnedNode)

    def test_node_has_unique_ids(self, mock_docker):
        result = spawn_nodes(3)
        ids = {n.node_id for n in result}
        assert len(ids) == 3

    def test_ports_increment_across_spawns(self, mock_docker):
        result = spawn_nodes(3)
        api_ports = [n.api_port for n in result]
        assert api_ports == sorted(set(api_ports))
        p2p_ports = [n.p2p_port for n in result]
        assert p2p_ports == sorted(set(p2p_ports))

    def test_first_node_uses_start_port(self, mock_docker):
        result = spawn_nodes(1)
        assert result[0].api_port == orch._API_PORT_START
        assert result[0].p2p_port == orch._P2P_PORT_START

    def test_nodes_registered_in_state(self, mock_docker):
        spawn_nodes(2)
        assert len(_nodes) == 2

    def test_container_run_called_with_network(self, mock_docker):
        client, _ = mock_docker
        spawn_nodes(1)
        _, kwargs = client.containers.run.call_args
        assert kwargs.get("network") == orch.DOCKER_NETWORK

    def test_container_run_passes_rendezvous_url(self, mock_docker):
        client, _ = mock_docker
        spawn_nodes(1, rendezvous_url="http://backend:8000")
        _, kwargs = client.containers.run.call_args
        env = kwargs.get("environment", {})
        assert env["RENDEZVOUS_URL"] == "http://backend:8000"

    def test_container_run_sets_advertise_host(self, mock_docker):
        client, _ = mock_docker
        result = spawn_nodes(1)
        _, kwargs = client.containers.run.call_args
        env = kwargs.get("environment", {})
        assert env["P2P_ADVERTISE_HOST"] == result[0].container_name

    def test_container_run_maps_correct_ports(self, mock_docker):
        client, _ = mock_docker
        result = spawn_nodes(1)
        _, kwargs = client.containers.run.call_args
        ports = kwargs.get("ports", {})
        assert "8000/tcp" in ports
        assert "9000/tcp" in ports
        assert ports["8000/tcp"] == result[0].api_port
        assert ports["9000/tcp"] == result[0].p2p_port

    def test_container_run_uses_node_image(self, mock_docker):
        client, _ = mock_docker
        spawn_nodes(1)
        args, kwargs = client.containers.run.call_args
        # image may be passed positionally or as keyword
        image = args[0] if args else kwargs.get("image")
        assert image == orch.NODE_IMAGE

    def test_raises_when_exceeding_max_count(self, mock_docker):
        # Fill up to limit first
        client, container = mock_docker
        for _ in range(NODE_MAX_COUNT):
            node_id = "fake"
            import uuid
            nid = str(uuid.uuid4())[:8]
            _nodes[nid] = SpawnedNode(
                node_id=nid,
                container_id="fakeid",
                container_name=f"aura-node-{nid}",
                api_port=9999,
                p2p_port=9998,
            )
        with pytest.raises(ValueError, match="NODE_MAX_COUNT"):
            spawn_nodes(1)

    def test_port_counters_rolled_back_on_failure(self, mock_docker):
        client, _ = mock_docker
        client.containers.run.side_effect = RuntimeError("Docker daemon unavailable")
        initial_api = orch._api_port_counter
        with pytest.raises(RuntimeError):
            spawn_nodes(1)
        assert orch._api_port_counter == initial_api


# ── list_nodes ────────────────────────────────────────────────────────────────

class TestListNodes:
    def test_empty_when_no_nodes_spawned(self):
        with patch("backend.orchestration.nodes._docker_client"):
            result = list_nodes()
        assert result == []

    def test_returns_all_spawned_nodes(self, mock_docker):
        spawn_nodes(3)
        result = list_nodes()
        assert len(result) == 3

    def test_syncs_status_from_docker(self, mock_docker):
        client, container = mock_docker
        container.status = "exited"
        spawn_nodes(1)
        result = list_nodes()
        assert result[0].status == "exited"

    def test_marks_removed_containers(self, mock_docker):
        import docker.errors
        client, _ = mock_docker
        spawn_nodes(1)
        client.containers.get.side_effect = docker.errors.NotFound("gone")
        result = list_nodes()
        assert result[0].status == "removed"


# ── stop_node ─────────────────────────────────────────────────────────────────

class TestStopNode:
    def test_stop_removes_from_registry(self, mock_docker):
        nodes = spawn_nodes(1)
        stop_node(nodes[0].node_id)
        assert nodes[0].node_id not in _nodes

    def test_stop_calls_container_stop_and_remove(self, mock_docker):
        client, container = mock_docker
        nodes = spawn_nodes(1)
        stop_node(nodes[0].node_id)
        container.stop.assert_called_once()
        container.remove.assert_called_once()

    def test_stop_unknown_node_raises_key_error(self, mock_docker):
        with pytest.raises(KeyError):
            stop_node("does-not-exist")

    def test_stop_already_gone_container_does_not_raise(self, mock_docker):
        import docker.errors
        client, container = mock_docker
        container.stop.side_effect = docker.errors.NotFound("already gone")
        nodes = spawn_nodes(1)
        stop_node(nodes[0].node_id)  # should not raise
        assert nodes[0].node_id not in _nodes


# ── stop_all_nodes ────────────────────────────────────────────────────────────

class TestStopAllNodes:
    def test_stops_all_nodes(self, mock_docker):
        spawn_nodes(3)
        stop_all_nodes()
        assert _nodes == {}

    def test_empty_nodes_is_noop(self, mock_docker):
        stop_all_nodes()  # should not raise

    def test_continues_after_partial_failure(self, mock_docker):
        """stop_all_nodes must not abort if one container fails to stop."""
        import docker.errors
        client, container = mock_docker
        container.stop.side_effect = docker.errors.NotFound("gone")
        spawn_nodes(2)
        stop_all_nodes()  # should not raise
        assert _nodes == {}
