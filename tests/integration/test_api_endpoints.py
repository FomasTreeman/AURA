"""
Integration tests for the AURA FastAPI application (backend/main.py).
Uses TestClient with mocked P2P/Ollama startup so no network or Docker is needed.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def api_client(tmp_path_factory):
    """
    TestClient with lifespan mocked:
    - Ollama check suppressed
    - P2P adapter replaced with a lightweight mock
    - Carbon scheduler replaced to avoid background tasks
    - init_db() redirected to a temp SQLite file
    """
    tmp = tmp_path_factory.mktemp("api_test")

    adapter = MagicMock()
    adapter.peer_id = "12D3KooWtestPeerIdXXXXXXXXXXXX"
    adapter.multiaddr = "/ip4/127.0.0.1/tcp/9000/p2p/12D3KooWtestPeerIdXXXXXXXXXXXX"
    adapter.get_peers.return_value = []
    adapter.start = AsyncMock()
    adapter.stop = AsyncMock()

    mdns_inst = MagicMock(); mdns_inst.start = AsyncMock(); mdns_inst.stop = AsyncMock()
    bootstrap_inst = MagicMock(); bootstrap_inst.start = AsyncMock(); bootstrap_inst.stop = AsyncMock()
    rendezvous_inst = MagicMock(); rendezvous_inst.start = AsyncMock(); rendezvous_inst.stop = AsyncMock()
    federated_inst = MagicMock()
    revocation_inst = MagicMock()

    scheduler = MagicMock()
    scheduler.start = AsyncMock()
    scheduler.stop = AsyncMock()
    scheduler._running = False
    scheduler._queue = []
    scheduler.get_queue_status.return_value = {
        "queued_tasks": 0, "tasks": [],
        "grid_intensity_gco2_kwh": 400.0, "is_low_carbon": False, "threshold_gco2_kwh": 200,
    }

    import backend.database.history as hist_mod
    original_db = hist_mod._DB_PATH
    hist_mod._DB_PATH = tmp / "chat_history.db"

    with (
        patch("backend.main.check_ollama", return_value=True),
        patch("backend.main.AuraP2PAdapter", return_value=adapter),
        patch("backend.main.MDNSDiscovery", return_value=mdns_inst),
        patch("backend.main.BootstrapDiscovery", return_value=bootstrap_inst),
        patch("backend.main.RendezvousDiscovery", return_value=rendezvous_inst),
        patch("backend.main.FederatedRetriever", return_value=federated_inst),
        patch("backend.main.RevocationManager", return_value=revocation_inst),
        patch("backend.main.CARBON_SCHEDULER", scheduler),
        patch("backend.observability.greenops.CARBON_SCHEDULER", scheduler),
    ):
        from backend.main import app
        with TestClient(app) as client:
            yield client

    hist_mod._DB_PATH = original_db


# ── /health ───────────────────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_returns_200(self, api_client):
        r = api_client.get("/health")
        assert r.status_code == 200

    def test_response_has_status_ok(self, api_client):
        r = api_client.get("/health")
        assert r.json()["status"] == "ok"

    def test_response_has_ollama_field(self, api_client):
        r = api_client.get("/health")
        assert "ollama" in r.json()

    def test_response_has_vector_store_field(self, api_client):
        r = api_client.get("/health")
        assert "vector_store" in r.json()


# ── /stats ────────────────────────────────────────────────────────────────────

class TestStatsEndpoint:
    def test_returns_200(self, api_client):
        r = api_client.get("/stats")
        assert r.status_code == 200

    def test_response_has_document_count(self, api_client):
        r = api_client.get("/stats")
        assert "document_count" in r.json()

    def test_document_count_is_integer(self, api_client):
        r = api_client.get("/stats")
        assert isinstance(r.json()["document_count"], int)


# ── /network/status ───────────────────────────────────────────────────────────

class TestNetworkStatus:
    def test_returns_200(self, api_client):
        r = api_client.get("/network/status")
        assert r.status_code == 200

    def test_response_has_running_field(self, api_client):
        data = api_client.get("/network/status").json()
        assert "running" in data

    def test_response_has_peer_count(self, api_client):
        data = api_client.get("/network/status").json()
        assert "peers" in data


# ── /network/peers ────────────────────────────────────────────────────────────

class TestNetworkPeers:
    def test_returns_200(self, api_client):
        r = api_client.get("/network/peers")
        assert r.status_code == 200

    def test_response_has_peers_list(self, api_client):
        data = api_client.get("/network/peers").json()
        assert "peers" in data
        assert isinstance(data["peers"], list)


# ── /rendezvous ───────────────────────────────────────────────────────────────

class TestRendezvousEndpoints:
    def test_register_returns_200(self, api_client):
        r = api_client.post("/rendezvous/register", json={
            "peer_id": "test-peer-1",
            "multiaddr": "/ip4/1.2.3.4/tcp/9000/p2p/test-peer-1",
        })
        assert r.status_code == 200
        assert r.json()["registered"] is True

    def test_register_missing_peer_id_returns_400(self, api_client):
        r = api_client.post("/rendezvous/register", json={
            "peer_id": "",
            "multiaddr": "/ip4/1.2.3.4/tcp/9000",
        })
        assert r.status_code == 400

    def test_peers_returns_registered_peer(self, api_client):
        api_client.post("/rendezvous/register", json={
            "peer_id": "test-peer-2",
            "multiaddr": "/ip4/5.6.7.8/tcp/9000/p2p/test-peer-2",
        })
        data = api_client.get("/rendezvous/peers").json()
        peer_ids = [p["peer_id"] for p in data["peers"]]
        assert "test-peer-2" in peer_ids

    def test_unregister_removes_peer(self, api_client):
        api_client.post("/rendezvous/register", json={
            "peer_id": "peer-to-remove",
            "multiaddr": "/ip4/9.9.9.9/tcp/9000/p2p/peer-to-remove",
        })
        r = api_client.delete("/rendezvous/unregister/peer-to-remove")
        assert r.status_code == 200
        assert r.json()["unregistered"] is True


# ── /documents ────────────────────────────────────────────────────────────────

class TestDocumentsEndpoint:
    def test_returns_200(self, api_client):
        r = api_client.get("/documents")
        assert r.status_code == 200

    def test_response_has_count_and_documents(self, api_client):
        data = api_client.get("/documents").json()
        assert "count" in data
        assert "documents" in data
        assert isinstance(data["documents"], list)

    def test_empty_store_returns_zero_count(self, api_client):
        data = api_client.get("/documents").json()
        assert data["count"] == 0


# ── /chat/history ─────────────────────────────────────────────────────────────

class TestChatHistoryEndpoints:
    def test_history_returns_200(self, api_client):
        r = api_client.get("/chat/history")
        assert r.status_code == 200

    def test_history_response_structure(self, api_client):
        data = api_client.get("/chat/history").json()
        assert "count" in data
        assert "sessions" in data
        assert isinstance(data["sessions"], list)

    def test_history_unknown_session_returns_404(self, api_client):
        r = api_client.get("/chat/history/non-existent-query-id")
        assert r.status_code == 404

    def test_history_limit_param_accepted(self, api_client):
        r = api_client.get("/chat/history?limit=10")
        assert r.status_code == 200


# ── /nodes (orchestration disabled) ──────────────────────────────────────────

class TestNodesEndpointsOrchDisabled:
    """When ORCHESTRATION_ENABLED=false (default in tests), spawn returns 403."""

    def test_list_nodes_returns_empty(self, api_client):
        r = api_client.get("/nodes")
        assert r.status_code == 200
        assert r.json()["count"] == 0

    def test_spawn_returns_403_when_disabled(self, api_client):
        r = api_client.post("/nodes/spawn", json={"count": 1})
        assert r.status_code == 403

    def test_stop_returns_403_when_disabled(self, api_client):
        r = api_client.delete("/nodes/fake-node-id")
        assert r.status_code == 403


# ── /ingest validation ────────────────────────────────────────────────────────

class TestIngestValidation:
    def test_ingest_nonexistent_directory_returns_400(self, api_client):
        r = api_client.post("/ingest", json={"directory": "/does/not/exist"})
        assert r.status_code == 400

    def test_query_empty_question_returns_400(self, api_client):
        r = api_client.post("/query", json={"question": ""})
        assert r.status_code == 400

    def test_query_whitespace_only_returns_400(self, api_client):
        r = api_client.post("/query", json={"question": "   "})
        assert r.status_code == 400


# ── /tombstones ───────────────────────────────────────────────────────────────

class TestTombstonesEndpoint:
    def test_returns_200(self, api_client):
        r = api_client.get("/tombstones")
        assert r.status_code == 200

    def test_response_has_cids_list(self, api_client):
        data = api_client.get("/tombstones").json()
        assert "cids" in data
        assert isinstance(data["cids"], list)
