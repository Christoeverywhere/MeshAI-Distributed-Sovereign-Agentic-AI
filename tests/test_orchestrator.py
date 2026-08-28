"""Pytest test suite for MeshAI Orchestrator.

Tests node registration, heartbeats, status detection, offline transitions,
reconnections, REST APIs, and database persistence.
"""

from datetime import datetime, timedelta, timezone
import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from orchestrator.config import settings
from orchestrator.database import init_db
from orchestrator.main import app
from orchestrator.models import NodeStatus
from orchestrator.node_manager import node_manager


@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    """Fixture to configure an isolated temporary SQLite database for each test."""
    temp_dir = tempfile.mkdtemp()
    test_db_path = os.path.join(temp_dir, "test_meshai.db")

    # Override settings and node_manager db_path
    monkeypatch.setattr(settings, "DATABASE_PATH", test_db_path)
    monkeypatch.setattr(node_manager, "db_path", test_db_path)

    # Initialize the test database schema
    init_db(test_db_path)

    yield test_db_path

    # Clean up test database file
    if os.path.exists(test_db_path):
        try:
            os.remove(test_db_path)
        except OSError:
            pass


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    with TestClient(app) as client:
        yield client


def test_server_starts_and_root_endpoint(client):
    """Verify that root endpoint returns operational info."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["system"] == "MeshAI Orchestrator"
    assert data["status"] == "running"
    assert "version" in data


def test_orchestrator_info_endpoint(client):
    """Verify host PC self-information endpoint."""
    response = client.get("/api/v1/orchestrator/info")
    assert response.status_code == 200
    data = response.json()
    assert "hostname" in data
    assert "operating_system" in data
    assert data["cpu_cores_logical"] > 0
    assert data["ram_total_mb"] > 0
    assert isinstance(data["local_ip_addresses"], list)


def test_system_status_empty(client):
    """Verify cluster status when no nodes are registered."""
    response = client.get("/api/v1/status")
    assert response.status_code == 200
    data = response.json()
    assert data["nodes_total"] == 0
    assert data["nodes_online"] == 0
    assert data["nodes_offline"] == 0


def test_node_registration_and_lookup(client):
    """Verify worker node registration and individual retrieval."""
    payload = {
        "node_id": "phone_01",
        "device_name": "Galaxy S23",
        "device_type": "android",
        "operating_system": "Android 14",
        "ram_mb": 8192,
        "cpu_cores": 8,
        "battery_percent": 85,
        "capabilities": ["ocr", "vision"],
        "port": 8080,
    }

    # Register node
    reg_response = client.post("/api/v1/nodes/register", json=payload)
    assert reg_response.status_code == 200
    reg_data = reg_response.json()
    assert reg_data["status"] == "registered"
    assert reg_data["node_id"] == "phone_01"

    # Lookup registered node
    get_response = client.get("/api/v1/nodes/phone_01")
    assert get_response.status_code == 200
    node_data = get_response.json()
    assert node_data["node_id"] == "phone_01"
    assert node_data["device_name"] == "Galaxy S23"
    assert node_data["ram_mb"] == 8192
    assert node_data["cpu_cores"] == 8
    assert node_data["battery_percent"] == 85
    assert "ocr" in node_data["capabilities"]
    assert "vision" in node_data["capabilities"]
    assert node_data["status"] == "ONLINE"


def test_duplicate_registration_updates_existing_node(client):
    """Verify that registering with an existing node_id updates records without duplication."""
    initial_payload = {
        "node_id": "phone_01",
        "device_name": "Galaxy S23",
        "ram_mb": 8192,
        "cpu_cores": 8,
        "battery_percent": 80,
        "capabilities": ["ocr"],
    }
    res1 = client.post("/api/v1/nodes/register", json=initial_payload)
    assert res1.status_code == 200
    assert res1.json()["status"] == "registered"

    # Updated payload with new capabilities and battery
    updated_payload = {
        "node_id": "phone_01",
        "device_name": "Galaxy S23 Ultra",
        "ram_mb": 12288,
        "cpu_cores": 8,
        "battery_percent": 95,
        "capabilities": ["ocr", "vision", "llm"],
    }
    res2 = client.post("/api/v1/nodes/register", json=updated_payload)
    assert res2.status_code == 200
    assert res2.json()["status"] == "updated"

    # Check that only one node exists and fields were updated
    nodes_res = client.get("/api/v1/nodes")
    nodes_list = nodes_res.json()
    assert len(nodes_list) == 1
    assert nodes_list[0]["device_name"] == "Galaxy S23 Ultra"
    assert nodes_list[0]["ram_mb"] == 12288
    assert set(nodes_list[0]["capabilities"]) == {"ocr", "vision", "llm"}


def test_list_nodes_and_system_metrics(client):
    """Verify listing multiple nodes and system metrics calculations."""
    nodes = [
        {
            "node_id": "phone_01",
            "device_name": "Pixel 7",
            "ram_mb": 8192,
            "cpu_cores": 8,
            "capabilities": ["ocr"],
        },
        {
            "node_id": "phone_02",
            "device_name": "Pixel 8",
            "ram_mb": 8192,
            "cpu_cores": 8,
            "capabilities": ["vision"],
        },
    ]

    for n in nodes:
        client.post("/api/v1/nodes/register", json=n)

    list_res = client.get("/api/v1/nodes")
    assert list_res.status_code == 200
    all_nodes = list_res.json()
    assert len(all_nodes) == 2

    status_res = client.get("/api/v1/status")
    status_data = status_res.json()
    assert status_data["nodes_total"] == 2
    assert status_data["nodes_online"] == 2
    assert status_data["nodes_offline"] == 0


def test_individual_node_not_found(client):
    """Verify 404 response for non-existent node lookup."""
    response = client.get("/api/v1/nodes/non_existent_node")
    assert response.status_code == 404


def test_heartbeat_updates_last_seen_and_battery(client):
    """Verify that heartbeat updates timestamps and battery status."""
    client.post(
        "/api/v1/nodes/register",
        json={
            "node_id": "phone_01",
            "device_name": "Galaxy S21",
            "ram_mb": 6144,
            "cpu_cores": 8,
            "battery_percent": 50,
        },
    )

    # Initial node state
    node_before = client.get("/api/v1/nodes/phone_01").json()

    # Send heartbeat with new battery level
    hb_response = client.post(
        "/api/v1/nodes/phone_01/heartbeat", json={"battery_percent": 75}
    )
    assert hb_response.status_code == 200
    assert hb_response.json()["status"] == "alive"

    node_after = client.get("/api/v1/nodes/phone_01").json()
    assert node_after["battery_percent"] == 75
    assert node_after["status"] == "ONLINE"


def test_heartbeat_unknown_node_returns_404(client):
    """Verify that sending a heartbeat for an unregistered node returns 404."""
    response = client.post(
        "/api/v1/nodes/unknown_phone/heartbeat", json={"battery_percent": 90}
    )
    assert response.status_code == 404


def test_node_removal(client):
    """Verify deletion of a registered node."""
    client.post(
        "/api/v1/nodes/register",
        json={
            "node_id": "phone_01",
            "device_name": "Device to delete",
            "ram_mb": 4096,
            "cpu_cores": 4,
        },
    )

    # Ensure it exists
    assert client.get("/api/v1/nodes/phone_01").status_code == 200

    # Delete node
    del_res = client.delete("/api/v1/nodes/phone_01")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "removed"

    # Lookup should now return 404
    assert client.get("/api/v1/nodes/phone_01").status_code == 404

    # Deleting again should return 404
    del_again = client.delete("/api/v1/nodes/phone_01")
    assert del_again.status_code == 404


def test_offline_detection_and_reconnection(client, setup_test_db):
    """Verify that nodes exceeding the timeout are marked OFFLINE and can reconnect to ONLINE."""
    client.post(
        "/api/v1/nodes/register",
        json={
            "node_id": "phone_test",
            "device_name": "Test Phone",
            "ram_mb": 4096,
            "cpu_cores": 4,
        },
    )

    # Simulate node last seen 30 seconds in the past
    past_time = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    from orchestrator.database import get_db

    with get_db(setup_test_db) as conn:
        conn.execute(
            "UPDATE nodes SET last_seen = ? WHERE node_id = ?",
            (past_time, "phone_test"),
        )

    # Run health check with 10s timeout
    marked = node_manager.check_and_update_offline_nodes(timeout_seconds=10)
    assert "phone_test" in marked

    # Node status should now be OFFLINE
    node = client.get("/api/v1/nodes/phone_test").json()
    assert node["status"] == "OFFLINE"

    # Status summary should show 1 offline node
    status_data = client.get("/api/v1/status").json()
    assert status_data["nodes_online"] == 0
    assert status_data["nodes_offline"] == 1

    # Heartbeat from the node should restore status to ONLINE
    hb_res = client.post(
        "/api/v1/nodes/phone_test/heartbeat", json={"battery_percent": 99}
    )
    assert hb_res.status_code == 200

    # Node status should now be ONLINE
    reconnected_node = client.get("/api/v1/nodes/phone_test").json()
    assert reconnected_node["status"] == "ONLINE"
    assert reconnected_node["battery_percent"] == 99
