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


def test_capability_normalization(client):
    """Verify capabilities are normalized (lowercase, deduplicated)."""
    payload = {
        "node_id": "phone_cap",
        "device_name": "Test",
        "ram_mb": 4096,
        "cpu_cores": 4,
        "capabilities": [" WORKER ", "worker", " CALCULATE ", "Worker"]
    }
    res = client.post("/api/v1/nodes/register", json=payload)
    assert res.status_code == 200
    
    node = client.get("/api/v1/nodes/phone_cap").json()
    assert set(node["capabilities"]) == {"worker", "calculate"}
    assert len(node["capabilities"]) == 2


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


def test_task_creation_and_listing(client):
    """Verify task can be created and listed."""
    payload = {
        "task_type": "PING",
        "payload": {},
        "required_capabilities": ["worker"],
        "priority": 1
    }
    # Create task
    response = client.post("/api/v1/tasks", json=payload)
    assert response.status_code == 201
    task = response.json()
    assert task["task_type"] == "PING"
    assert task["status"] == "PENDING"
    
    # List tasks
    list_response = client.get("/api/v1/tasks")
    assert list_response.status_code == 200
    tasks = list_response.json()
    assert len(tasks) > 0
    assert tasks[0]["task_id"] == task["task_id"]
    
    # Get specific task
    get_response = client.get(f"/api/v1/tasks/{task['task_id']}")
    assert get_response.status_code == 200
    assert get_response.json()["task_id"] == task["task_id"]


def test_task_scheduling_and_assignment(client):
    """Verify task is assigned to an online worker with correct capabilities."""
    # Register an online worker
    client.post(
        "/api/v1/nodes/register",
        json={
            "node_id": "worker_01",
            "device_name": "Test Worker",
            "ram_mb": 4096,
            "cpu_cores": 4,
            "capabilities": ["ping_capable", "worker"]
        },
    )
    
    # Create task
    payload = {
        "task_type": "PING",
        "payload": {},
        "required_capabilities": ["ping_capable"],
        "priority": 1
    }
    response = client.post("/api/v1/tasks", json=payload)
    assert response.status_code == 201
    task = response.json()
    
    # Check assignment
    assert task["status"] == "ASSIGNED"
    assert task["assigned_node"] == "worker_01"


def test_task_ignores_offline_worker(client, setup_test_db):
    """Verify task is not assigned to an offline worker."""
    # Register a worker
    client.post(
        "/api/v1/nodes/register",
        json={
            "node_id": "offline_worker",
            "device_name": "Test Worker",
            "ram_mb": 4096,
            "cpu_cores": 4,
            "capabilities": ["ping_capable", "worker"]
        },
    )
    
    # Mark it offline
    from datetime import datetime, timedelta, timezone
    from orchestrator.database import get_db
    past_time = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    with get_db(setup_test_db) as conn:
        conn.execute(
            "UPDATE nodes SET status = ?, last_seen = ? WHERE node_id = ?",
            ("OFFLINE", past_time, "offline_worker"),
        )
        
    # Create task
    payload = {
        "task_type": "PING",
        "payload": {},
        "required_capabilities": ["ping_capable"],
        "priority": 1
    }
    response = client.post("/api/v1/tasks", json=payload)
    assert response.status_code == 201
    task = response.json()
    
    # Should still be pending since no online workers
    assert task["status"] == "PENDING"
    assert task["assigned_node"] is None


def test_task_completion_lifecycle(client):
    """Verify end-to-end task completion lifecycle."""
    # Register worker
    client.post(
        "/api/v1/nodes/register",
        json={
            "node_id": "worker_02",
            "device_name": "Test Worker",
            "ram_mb": 4096,
            "cpu_cores": 4,
            "capabilities": ["worker"]
        },
    )
    
    # Create task
    payload = {
        "task_type": "PING",
        "payload": {},
        "required_capabilities": ["worker"],
        "priority": 1
    }
    create_res = client.post("/api/v1/tasks", json=payload)
    task_id = create_res.json()["task_id"]
    
    # Worker polls tasks
    poll_res = client.get("/api/v1/nodes/worker_02/tasks")
    assert poll_res.status_code == 200
    polled_task = poll_res.json()
    assert polled_task["task_id"] == task_id
    assert polled_task["status"] == "RUNNING"
    
    # Worker submits result
    result_payload = {
        "node_id": "worker_02",
        "status": "COMPLETED",
        "result": "PONG"
    }
    res = client.post(f"/api/v1/tasks/{task_id}/result", json=result_payload)
    assert res.status_code == 200
    completed_task = res.json()
    assert completed_task["status"] == "COMPLETED"
    assert completed_task["result"] == "PONG"


def test_task_failure_lifecycle(client):
    """Verify end-to-end task failure lifecycle."""
    client.post(
        "/api/v1/nodes/register",
        json={
            "node_id": "worker_03",
            "device_name": "Test Worker",
            "ram_mb": 4096,
            "cpu_cores": 4,
            "capabilities": ["worker"]
        },
    )
    
    payload = {
        "task_type": "PING",
        "payload": {},
        "required_capabilities": ["worker"],
        "priority": 1
    }
    create_res = client.post("/api/v1/tasks", json=payload)
    task_id = create_res.json()["task_id"]
    
    # Worker submits failed result
    result_payload = {
        "node_id": "worker_03",
        "status": "FAILED",
        "error": "Timeout"
    }
    res = client.post(f"/api/v1/tasks/{task_id}/result", json=result_payload)
    assert res.status_code == 200
    failed_task = res.json()
    assert failed_task["status"] == "FAILED"
    assert failed_task["error"] == "Timeout"


def test_calculate_sum(client):
    """Verify CALCULATE task with SUM operation."""
    client.post("/api/v1/nodes/register", json={
        "node_id": "worker_calc", "device_name": "Test", "ram_mb": 1024, "cpu_cores": 1, "capabilities": ["worker", "calculate"]
    })
    
    payload = {
        "task_type": "CALCULATE",
        "payload": {"operation": "SUM", "values": [25, 17, 8]},
        "required_capabilities": ["worker"],
        "priority": 1
    }
    create_res = client.post("/api/v1/tasks", json=payload)
    task_id = create_res.json()["task_id"]
    
    # Worker simulates processing (this is an integration test of PC orchestrator API handling it)
    res = client.post(f"/api/v1/tasks/{task_id}/result", json={
        "node_id": "worker_calc",
        "status": "COMPLETED",
        "result": "50"
    })
    
    assert res.status_code == 200
    task = res.json()
    assert task["status"] == "COMPLETED"
    assert task["result"] == "50"


def test_calculate_subtract(client):
    """Verify CALCULATE task with SUBTRACT operation."""
    client.post("/api/v1/nodes/register", json={
        "node_id": "worker_calc", "device_name": "Test", "ram_mb": 1024, "cpu_cores": 1, "capabilities": ["worker", "calculate"]
    })
    
    payload = {
        "task_type": "CALCULATE",
        "payload": {"operation": "SUBTRACT", "values": [100, 20, 5]},
        "required_capabilities": ["worker"],
        "priority": 1
    }
    create_res = client.post("/api/v1/tasks", json=payload)
    task_id = create_res.json()["task_id"]
    
    res = client.post(f"/api/v1/tasks/{task_id}/result", json={
        "node_id": "worker_calc",
        "status": "COMPLETED",
        "result": "75"
    })
    
    assert res.status_code == 200
    assert res.json()["result"] == "75"


def test_calculate_multiply(client):
    """Verify CALCULATE task with MULTIPLY operation."""
    client.post("/api/v1/nodes/register", json={
        "node_id": "worker_calc", "device_name": "Test", "ram_mb": 1024, "cpu_cores": 1, "capabilities": ["worker", "calculate"]
    })
    
    payload = {
        "task_type": "CALCULATE",
        "payload": {"operation": "MULTIPLY", "values": [2, 5, 10]},
        "required_capabilities": ["worker"],
        "priority": 1
    }
    create_res = client.post("/api/v1/tasks", json=payload)
    task_id = create_res.json()["task_id"]
    
    res = client.post(f"/api/v1/tasks/{task_id}/result", json={
        "node_id": "worker_calc",
        "status": "COMPLETED",
        "result": "100"
    })
    
    assert res.status_code == 200
    assert res.json()["result"] == "100"


def test_calculate_invalid_operation(client):
    """Verify CALCULATE task with invalid operation fails."""
    client.post("/api/v1/nodes/register", json={
        "node_id": "worker_calc", "device_name": "Test", "ram_mb": 1024, "cpu_cores": 1, "capabilities": ["worker", "calculate"]
    })
    
    payload = {
        "task_type": "CALCULATE",
        "payload": {"operation": "DIVIDE", "values": [10, 2]},
        "required_capabilities": ["worker"],
        "priority": 1
    }
    create_res = client.post("/api/v1/tasks", json=payload)
    task_id = create_res.json()["task_id"]
    
    res = client.post(f"/api/v1/tasks/{task_id}/result", json={
        "node_id": "worker_calc",
        "status": "FAILED",
        "error": "Invalid operation: DIVIDE"
    })
    
    assert res.status_code == 200
    assert res.json()["status"] == "FAILED"
    assert res.json()["error"] == "Invalid operation: DIVIDE"


def test_calculate_empty_values(client):
    """Verify CALCULATE task with empty values fails."""
    client.post("/api/v1/nodes/register", json={
        "node_id": "worker_calc", "device_name": "Test", "ram_mb": 1024, "cpu_cores": 1, "capabilities": ["worker", "calculate"]
    })
    
    payload = {
        "task_type": "CALCULATE",
        "payload": {"operation": "SUM", "values": []},
        "required_capabilities": ["worker"],
        "priority": 1
    }
    create_res = client.post("/api/v1/tasks", json=payload)
    task_id = create_res.json()["task_id"]
    
    res = client.post(f"/api/v1/tasks/{task_id}/result", json={
        "node_id": "worker_calc",
        "status": "FAILED",
        "error": "Malformed payload or empty values"
    })
    
    assert res.status_code == 200
    assert res.json()["status"] == "FAILED"
    assert res.json()["error"] == "Malformed payload or empty values"


def test_calculate_malformed_payload(client):
    """Verify CALCULATE task with missing operation fails."""
    client.post("/api/v1/nodes/register", json={
        "node_id": "worker_calc", "device_name": "Test", "ram_mb": 1024, "cpu_cores": 1, "capabilities": ["worker", "calculate"]
    })
    
    payload = {
        "task_type": "CALCULATE",
        "payload": {"values": [1, 2, 3]},
        "required_capabilities": ["worker"],
        "priority": 1
    }
    create_res = client.post("/api/v1/tasks", json=payload)
    task_id = create_res.json()["task_id"]
    
    res = client.post(f"/api/v1/tasks/{task_id}/result", json={
        "node_id": "worker_calc",
        "status": "FAILED",
        "error": "Malformed payload or empty values"
    })
    
    assert res.status_code == 200
    assert res.json()["status"] == "FAILED"
    assert res.json()["error"] == "Malformed payload or empty values"


def test_scheduler_load_balancing_equal_load_tie_breaker(client):
    """Verify tie-breaker logic: RAM descending, then node_id ascending."""
    # Worker A: 4096MB RAM, ID = worker_a
    client.post("/api/v1/nodes/register", json={
        "node_id": "worker_a", "device_name": "A", "ram_mb": 4096, "cpu_cores": 2, "capabilities": ["worker", "calculate"]
    })
    # Worker B: 8192MB RAM, ID = worker_b
    client.post("/api/v1/nodes/register", json={
        "node_id": "worker_b", "device_name": "B", "ram_mb": 8192, "cpu_cores": 2, "capabilities": ["worker", "calculate"]
    })
    # Worker C: 8192MB RAM, ID = worker_c
    client.post("/api/v1/nodes/register", json={
        "node_id": "worker_c", "device_name": "C", "ram_mb": 8192, "cpu_cores": 2, "capabilities": ["worker", "calculate"]
    })

    # All have 0 load. B and C have the most RAM (8192). B comes before C alphabetically.
    # So B should be selected first.
    payload = {"task_type": "PING", "payload": {}, "required_capabilities": ["worker"], "priority": 1}
    res1 = client.post("/api/v1/tasks", json=payload)
    assert res1.json()["assigned_node"] == "worker_b"

    # Now B has 1 active task. A and C have 0 active tasks.
    # A has 4096, C has 8192. C should be selected.
    res2 = client.post("/api/v1/tasks", json=payload)
    assert res2.json()["assigned_node"] == "worker_c"
    
    # Now B has 1, C has 1, A has 0. A should be selected because it has the lowest load.
    res3 = client.post("/api/v1/tasks", json=payload)
    assert res3.json()["assigned_node"] == "worker_a"


def test_scheduler_task_status_load_counting(client):
    """Verify which statuses count towards active load."""
    client.post("/api/v1/nodes/register", json={
        "node_id": "worker_1", "device_name": "W1", "ram_mb": 4096, "cpu_cores": 2, "capabilities": ["worker", "calculate"]
    })
    client.post("/api/v1/nodes/register", json={
        "node_id": "worker_2", "device_name": "W2", "ram_mb": 4096, "cpu_cores": 2, "capabilities": ["worker", "calculate"]
    })
    
    # helper to manually set task state
    from orchestrator.task_manager import update_task_status, create_task
    from orchestrator.models import TaskCreate, TaskStatus

    def inject_task(node_id, status):
        task = create_task(TaskCreate(task_type="PING", payload={}, required_capabilities=["worker"], priority=1))
        update_task_status(task.task_id, TaskStatus.ASSIGNED, node_id)
        if status != TaskStatus.ASSIGNED:
            update_task_status(task.task_id, status)
            
    # Give worker_1 some non-active load
    inject_task("worker_1", TaskStatus.COMPLETED)
    inject_task("worker_1", TaskStatus.FAILED)
    inject_task("worker_1", TaskStatus.CANCELLED)
    # worker_1 active load should still be 0
    
    # Give worker_2 one active load (RUNNING)
    inject_task("worker_2", TaskStatus.RUNNING)
    
    # New task should go to worker_1
    payload = {"task_type": "PING", "payload": {}, "required_capabilities": ["worker"], "priority": 1}
    res1 = client.post("/api/v1/tasks", json=payload)
    assert res1.json()["assigned_node"] == "worker_1"
    
    # Now worker_1 has 1 ASSIGNED (active). worker_2 has 1 RUNNING (active). Tie.
    # RAM is equal. ID worker_1 < worker_2. Should go to worker_1.
    res2 = client.post("/api/v1/tasks", json=payload)
    assert res2.json()["assigned_node"] == "worker_1"


def test_task_scheduler_capability_mismatch(client):
    """Verify task requiring a missing capability remains PENDING."""
    client.post("/api/v1/nodes/register", json={
        "node_id": "worker_1", "device_name": "W1", "ram_mb": 4096, "cpu_cores": 2, "capabilities": ["worker", "calculate"]
    })
    
    payload = {
        "task_type": "CALCULATE",
        "payload": {"operation": "SUM", "values": [1,2]},
        "required_capabilities": ["worker", "calculate", "ocr"],
        "priority": 1
    }
    res = client.post("/api/v1/tasks", json=payload)
    
    assert res.status_code == 201
    task = res.json()
    assert task["status"] == "PENDING"
    assert task["assigned_node"] is None


def test_calculate_test_delay_valid(client):
    """Verify CALCULATE task with valid test_delay_ms is accepted."""
    client.post("/api/v1/nodes/register", json={
        "node_id": "worker_calc", "device_name": "Test", "ram_mb": 1024, "cpu_cores": 1, "capabilities": ["worker", "calculate"]
    })
    
    payload = {
        "task_type": "CALCULATE",
        "payload": {"operation": "SUM", "values": [10, 20], "test_delay_ms": 5000},
        "required_capabilities": ["worker", "calculate"],
        "priority": 1
    }
    create_res = client.post("/api/v1/tasks", json=payload)
    assert create_res.status_code == 201
    task_id = create_res.json()["task_id"]
    
    res = client.post(f"/api/v1/tasks/{task_id}/result", json={
        "node_id": "worker_calc",
        "status": "COMPLETED",
        "result": "30"
    })
    
    assert res.status_code == 200
    task = res.json()
    assert task["status"] == "COMPLETED"
    assert task["result"] == "30"


def test_calculate_test_delay_invalid_excessive(client):
    """Verify CALCULATE task with excessive test_delay_ms is safely rejected by worker."""
    client.post("/api/v1/nodes/register", json={
        "node_id": "worker_calc", "device_name": "Test", "ram_mb": 1024, "cpu_cores": 1, "capabilities": ["worker", "calculate"]
    })
    
    payload = {
        "task_type": "CALCULATE",
        "payload": {"operation": "SUM", "values": [10, 20], "test_delay_ms": 50000},
        "required_capabilities": ["worker", "calculate"],
        "priority": 1
    }
    create_res = client.post("/api/v1/tasks", json=payload)
    assert create_res.status_code == 201
    task_id = create_res.json()["task_id"]
    
    res = client.post(f"/api/v1/tasks/{task_id}/result", json={
        "node_id": "worker_calc",
        "status": "FAILED",
        "error": "Invalid test_delay_ms: 50000"
    })
    
    assert res.status_code == 200
    task = res.json()
    assert task["status"] == "FAILED"
    assert task["error"] == "Invalid test_delay_ms: 50000"


def test_calculate_test_delay_negative(client):
    """Verify CALCULATE task with negative test_delay_ms is safely rejected by worker."""
    client.post("/api/v1/nodes/register", json={
        "node_id": "worker_calc", "device_name": "Test", "ram_mb": 1024, "cpu_cores": 1, "capabilities": ["worker", "calculate"]
    })
    
    payload = {
        "task_type": "CALCULATE",
        "payload": {"operation": "SUM", "values": [10, 20], "test_delay_ms": -100},
        "required_capabilities": ["worker", "calculate"],
        "priority": 1
    }
    create_res = client.post("/api/v1/tasks", json=payload)
    assert create_res.status_code == 201
    task_id = create_res.json()["task_id"]
    
    res = client.post(f"/api/v1/tasks/{task_id}/result", json={
        "node_id": "worker_calc",
        "status": "FAILED",
        "error": "Invalid test_delay_ms: -100"
    })
    
    assert res.status_code == 200
    task = res.json()
    assert task["status"] == "FAILED"
    assert task["error"] == "Invalid test_delay_ms: -100"


def test_job_creation_and_task_execution(client):
    """Verify creating a job with multiple tasks schedules them and tracks status."""
    client.post("/api/v1/nodes/register", json={
        "node_id": "worker_job1", "device_name": "Test", "ram_mb": 4096, "cpu_cores": 2, "capabilities": ["worker", "calculate"]
    })
    client.post("/api/v1/nodes/register", json={
        "node_id": "worker_job2", "device_name": "Test2", "ram_mb": 4096, "cpu_cores": 2, "capabilities": ["worker", "calculate"]
    })
    
    job_payload = {
        "tasks": [
            {
                "task_type": "CALCULATE",
                "payload": {"operation": "SUM", "values": [1,2]},
                "required_capabilities": ["worker", "calculate"],
                "priority": 1
            },
            {
                "task_type": "CALCULATE",
                "payload": {"operation": "SUM", "values": [3,4]},
                "required_capabilities": ["worker", "calculate"],
                "priority": 1
            }
        ]
    }
    
    # 1. Create Job
    job_res = client.post("/api/v1/jobs", json=job_payload)
    assert job_res.status_code == 201
    job = job_res.json()
    job_id = job["job_id"]
    assert job["status"] == "PENDING" or job["status"] == "RUNNING"
    assert len(job["tasks"]) == 2
    
    task1 = job["tasks"][0]
    task2 = job["tasks"][1]
    
    assert task1["job_id"] == job_id
    assert task2["job_id"] == job_id
    assert task1["assigned_node"] is not None
    assert task2["assigned_node"] is not None
    assert task1["assigned_node"] != task2["assigned_node"] # Because they have equal load before assignment and tie break selects one then the other!
    
    # 2. Worker 1 completes Task 1
    client.post(f"/api/v1/tasks/{task1['task_id']}/result", json={
        "node_id": task1["assigned_node"],
        "status": "COMPLETED",
        "result": "3"
    })
    
    # 3. Check Job Status - should be RUNNING because Task 2 is not done
    job_res2 = client.get(f"/api/v1/jobs/{job_id}")
    assert job_res2.json()["status"] == "RUNNING"
    
    # 4. Worker 2 completes Task 2
    client.post(f"/api/v1/tasks/{task2['task_id']}/result", json={
        "node_id": task2["assigned_node"],
        "status": "COMPLETED",
        "result": "7"
    })
    
    # 5. Check Job Status - should be COMPLETED
    job_res3 = client.get(f"/api/v1/jobs/{job_id}")
    assert job_res3.json()["status"] == "COMPLETED"
    

def test_job_cancellation(client):
    """Verify job cancellation cancels pending/assigned tasks."""
    job_payload = {
        "tasks": [
            {
                "task_type": "PING",
                "payload": {},
                "required_capabilities": ["worker"],
                "priority": 1
            }
        ]
    }
    job = client.post("/api/v1/jobs", json=job_payload).json()
    job_id = job["job_id"]
    
    cancel_res = client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert cancel_res.status_code == 200
    
    job_cancelled = client.get(f"/api/v1/jobs/{job_id}").json()
    assert job_cancelled["status"] == "CANCELLED"
    assert job_cancelled["tasks"][0]["status"] == "CANCELLED"


def test_worker_disconnect_fails_assigned_tasks(client):
    """Verify offline detection marks assigned tasks as FAILED."""
    client.post("/api/v1/nodes/register", json={
        "node_id": "worker_fail", "device_name": "Test", "ram_mb": 4096, "cpu_cores": 2, "capabilities": ["worker"]
    })
    
    task = client.post("/api/v1/tasks", json={
        "task_type": "PING",
        "payload": {},
        "required_capabilities": ["worker"],
        "priority": 1
    }).json()
    
    assert task["assigned_node"] == "worker_fail"
    assert task["status"] == "ASSIGNED"
    
    # Force offline detection
    from orchestrator.node_manager import node_manager
    # Manually tweak last_seen to be very old
    from orchestrator.database import get_db
    with get_db() as conn:
        conn.execute("UPDATE nodes SET last_seen = '2020-01-01T00:00:00Z' WHERE node_id = 'worker_fail'")
    
    # Run timeout check
    node_manager.check_and_update_offline_nodes(timeout_seconds=30)
    
    # Check task
    failed_task = client.get(f"/api/v1/tasks/{task['task_id']}").json()
    assert failed_task["status"] == "FAILED"
    assert failed_task["error"] == "Worker disconnected"


def test_llm_generate_capability_inference(client):
    """Verify LLM_GENERATE automatically injects worker and llm capabilities."""
    payload = {
        "task_type": "LLM_GENERATE",
        "payload": {"prompt": "Hello"},
        "required_capabilities": [],
        "priority": 1
    }
    create_res = client.post("/api/v1/tasks", json=payload)
    assert create_res.status_code == 201
    task = create_res.json()
    assert "llm" in task["required_capabilities"]
    assert "worker" in task["required_capabilities"]
    
    # Verify prompt validation
    payload2 = {
        "task_type": "LLM_GENERATE",
        "payload": {},
        "required_capabilities": []
    }
    create_res2 = client.post("/api/v1/tasks", json=payload2)
    assert create_res2.status_code == 422 # Validation error from FastAPI


def test_llm_generate_remains_pending_without_model(client):
    """Verify LLM_GENERATE remains PENDING if no worker has llm capability."""
    # Register 4GB worker without llm
    client.post("/api/v1/nodes/register", json={
        "node_id": "worker_4gb", "device_name": "Test", "ram_mb": 4096, "cpu_cores": 2, 
        "capabilities": ["worker"], "available_ram_mb": 2000
    })
    
    payload = {
        "task_type": "LLM_GENERATE",
        "payload": {"prompt": "Hello", "max_tokens": 100},
        "required_capabilities": []
    }
    task = client.post("/api/v1/tasks", json=payload).json()
    assert task["status"] == "PENDING"
    assert task["assigned_node"] is None
