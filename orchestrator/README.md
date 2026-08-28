# MeshAI — Distributed Sovereign Agentic AI
## Step 1: MeshAI Node Network Orchestrator

MeshAI is a local, air-gapped distributed AI platform that coordinates trusted smartphones, laptops, and GPU machines across a local network to execute AI workloads.

This implementation covers **Step 1: The MeshAI Node Network Orchestrator** on Windows PC, providing node discovery, hardware registration, periodic heartbeat tracking, dynamic offline detection, reconnection handling, SQLite persistence, and REST APIs.

---

## 1. Target Architecture

```
                    ┌─────────────────────────┐
                    │      USER / CLIENT      │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │   MeshAI ORCHESTRATOR   │
                    │      (PC / Laptop)      │
                    │     FastAPI / Uvicorn   │
                    └────────────┬────────────┘
                                 │
                   Local Wi-Fi / LAN Network
                                 │
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                       ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  Android Worker  │    │  Android Worker  │    │  Android Worker  │
│     phone_01     │    │     phone_02     │    │     phone_03     │
│  [ocr, vision]   │    │ [ocr, retrieval] │    │  [vision, llm]   │
└──────────────────┘    └──────────────────┘    └──────────────────┘
```

The orchestrator operates 100% locally on your local network/Wi-Fi with zero external cloud dependencies or internet access requirements.

---

## 2. Project Structure & File Descriptions

```
MeshAI/
│
├── orchestrator/
│   ├── __init__.py          # Marks orchestrator as a Python package
│   ├── main.py              # FastAPI app, API routes, host info, lifespan & logging configuration
│   ├── config.py            # Centralized settings (HOST, PORT, timeouts, db path) & env overrides
│   ├── database.py          # SQLite database connection pool, WAL mode, table auto-creation
│   ├── models.py            # Pydantic v2 schemas for request validation & API responses
│   ├── node_manager.py      # Core business logic: registration, heartbeats, status transitions, queries
│   ├── health_monitor.py    # Background async task checking heartbeats & marking inactive nodes OFFLINE
│   ├── requirements.txt     # Python dependencies (FastAPI, Uvicorn, Pydantic, psutil, pytest, etc.)
│   ├── .gitignore           # Git ignore rules for virtual environments, SQLite databases, and caches
│   └── README.md            # Complete documentation, setup guide, and API reference
│
├── data/
│   └── meshai.db            # Persistent SQLite database (automatically generated on startup)
│
└── tests/
    ├── __init__.py          # Marks tests as a Python package
    ├── test_orchestrator.py # Pytest test suite covering all endpoints, persistence, and state transitions
    └── fake_worker.py       # CLI simulator acting as Android worker devices for multi-node testing
```

### Detailed Purpose of Every File:

| File | Purpose |
|---|---|
| `orchestrator/main.py` | Entry point for FastAPI. Defines REST endpoints (`/`, `/api/v1/status`, `/api/v1/orchestrator/info`, `/api/v1/nodes/*`), handles client IP extraction, and manages server startup/shutdown lifespan. |
| `orchestrator/config.py` | Central configuration object. Controls host/port binding (`0.0.0.0:8000`), heartbeat interval (`3s`), node timeout threshold (`10s`), and database path (`data/meshai.db`). |
| `orchestrator/database.py` | Manages SQLite connection lifecycle, schema initialization, and transactional safety. Uses WAL mode for fast concurrent operations. |
| `orchestrator/models.py` | Pydantic data models enforcing strict schema validation on inbound payloads (RAM, CPU cores, battery level, AI capabilities) and serializing JSON responses. |
| `orchestrator/node_manager.py` | Encapsulates all node CRUD operations, prevents duplicate records, transitions node statuses between `ONLINE` and `OFFLINE`, and handles reconnections. |
| `orchestrator/health_monitor.py` | Asynchronous background worker running alongside FastAPI that continuously sweeps registered nodes and marks nodes as `OFFLINE` if they stop heartbeating. |
| `orchestrator/requirements.txt` | Lists exact production and testing dependencies. |
| `orchestrator/.gitignore` | Prevents runtime database files (`*.db`, `*.db-wal`), virtual environments, and caches from entering version control. |
| `tests/test_orchestrator.py` | Automated test suite verifying node registration, duplicate updates, heartbeat timestamps, 404 handling, deletions, and offline/reconnection logic using `TestClient`. |
| `tests/fake_worker.py` | Python script simulating an Android smartphone. Registers itself with custom hardware specs/capabilities and streams periodic heartbeats to the orchestrator. |

---

## 3. Windows Setup & Installation Instructions

Follow these exact steps in PowerShell or Command Prompt:

### Step 3.1: Navigate to Workspace and Create Virtual Environment
```powershell
cd d:\MeshAI
python -m venv .venv
```

### Step 3.2: Activate Virtual Environment
```powershell
.venv\Scripts\activate
```

### Step 3.3: Install Dependencies
```powershell
pip install -r orchestrator\requirements.txt
```

### Step 3.4: Start the Orchestrator Server
```powershell
uvicorn orchestrator.main:app --host 0.0.0.0 --port 8000 --reload
```

Output:
```
[INFO] Initializing database at D:\MeshAI\data\meshai.db
[INFO] Database initialized successfully
[INFO] Health monitor loop started (check interval: 3s, timeout threshold: 10s)
[INFO] MeshAI Orchestrator started
[INFO] Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

---

## 4. Local Network & Wi-Fi Access

The orchestrator listens on `0.0.0.0:8000`, allowing any phone or computer on your local Wi-Fi / Ethernet to connect.

### Find Your PC's Local IP Address:
Run in PowerShell:
```powershell
ipconfig
```
Look for **IPv4 Address** under your active Wi-Fi or Ethernet adapter (for example: `192.168.1.105`).

- **Local PC Testing:** Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **Local Network Devices (Android phones):** Connect to `http://<YOUR_PC_LOCAL_IP>:8000` (e.g. `http://192.168.1.105:8000/api/v1/nodes/register`)

---

## 5. Multi-Node Demonstration (Simulating 3 Android Phones)

You can simulate multiple Android phones running concurrently using `tests/fake_worker.py`.

Open **three separate PowerShell terminal windows** (with `.venv` activated):

### Terminal 1 — Worker 1 (Galaxy S23 - OCR & Vision):
```powershell
cd d:\MeshAI
.venv\Scripts\activate
python tests\fake_worker.py --node-id phone_01 --device-name "Galaxy S23" --ram 8192 --cores 8 --battery 90 --capabilities "ocr,vision"
```

### Terminal 2 — Worker 2 (Pixel 8 - OCR & Retrieval):
```powershell
cd d:\MeshAI
.venv\Scripts\activate
python tests\fake_worker.py --node-id phone_02 --device-name "Pixel 8" --ram 8192 --cores 8 --battery 85 --capabilities "ocr,retrieval"
```

### Terminal 3 — Worker 3 (OnePlus 11 - Vision & LLM):
```powershell
cd d:\MeshAI
.venv\Scripts\activate
python tests\fake_worker.py --node-id phone_03 --device-name "OnePlus 11" --ram 16384 --cores 8 --battery 95 --capabilities "vision,llm"
```

### Step 5.1: Check Cluster Status (All 3 Online)
Open another terminal or browser and query:
```powershell
curl http://127.0.0.1:8000/api/v1/status
```
Response:
```json
{
  "system": "MeshAI",
  "status": "running",
  "version": "0.1.0",
  "nodes_total": 3,
  "nodes_online": 3,
  "nodes_offline": 0
}
```

List all nodes:
```powershell
curl http://127.0.0.1:8000/api/v1/nodes
```
```json
[
  {
    "node_id": "phone_01",
    "device_name": "Galaxy S23",
    "status": "ONLINE",
    "ram_mb": 8192,
    "cpu_cores": 8,
    "battery_percent": 90,
    "capabilities": ["ocr", "vision"]
  },
  {
    "node_id": "phone_02",
    "device_name": "Pixel 8",
    "status": "ONLINE",
    "ram_mb": 8192,
    "cpu_cores": 8,
    "battery_percent": 85,
    "capabilities": ["ocr", "retrieval"]
  },
  {
    "node_id": "phone_03",
    "device_name": "OnePlus 11",
    "status": "ONLINE",
    "ram_mb": 16384,
    "cpu_cores": 8,
    "battery_percent": 95,
    "capabilities": ["vision", "llm"]
  }
]
```

### Step 5.2: Stop Worker 2 & Observe Offline Detection
Press `Ctrl+C` in **Terminal 2** (Worker 2).
Within 10 seconds, the orchestrator logs:
```
[WARNING] Node offline: phone_02
```
Checking cluster status:
```powershell
curl http://127.0.0.1:8000/api/v1/status
```
Response:
```json
{
  "system": "MeshAI",
  "status": "running",
  "version": "0.1.0",
  "nodes_total": 3,
  "nodes_online": 2,
  "nodes_offline": 1
}
```

### Step 5.3: Restart Worker 2 & Observe Reconnection
Run the worker 2 command again in **Terminal 2**:
```powershell
python tests\fake_worker.py --node-id phone_02 --device-name "Pixel 8" --ram 8192 --cores 8 --battery 85 --capabilities "ocr,retrieval"
```
The orchestrator logs:
```
[INFO] Node reconnected: phone_02
```
The node is seamlessly returned to `ONLINE` status without creating duplicate entries.

---

## 6. REST API Reference

### 6.1 Root Service Check
- **Endpoint:** `GET /`
- **Response:**
```json
{
  "system": "MeshAI Orchestrator",
  "version": "0.1.0",
  "status": "running"
}
```

### 6.2 Host PC Self Diagnostics
- **Endpoint:** `GET /api/v1/orchestrator/info`
- **Response:**
```json
{
  "hostname": "MY-PC",
  "operating_system": "Windows 11 ...",
  "cpu_cores_physical": 8,
  "cpu_cores_logical": 16,
  "ram_total_mb": 32768,
  "ram_available_mb": 18450,
  "ram_used_percent": 43.7,
  "local_ip_addresses": ["192.168.1.105"]
}
```

### 6.3 Register / Update Node
- **Endpoint:** `POST /api/v1/nodes/register`
- **Request Body:**
```json
{
  "node_id": "phone_01",
  "device_name": "Galaxy S23",
  "device_type": "android",
  "operating_system": "Android 14",
  "ram_mb": 8192,
  "cpu_cores": 8,
  "battery_percent": 82,
  "capabilities": ["ocr", "vision"],
  "port": 8080
}
```
- **Response:**
```json
{
  "status": "registered",
  "node_id": "phone_01",
  "message": "Node successfully registered with MeshAI"
}
```

### 6.4 Node Heartbeat
- **Endpoint:** `POST /api/v1/nodes/{node_id}/heartbeat`
- **Request Body:**
```json
{
  "battery_percent": 78
}
```
- **Response:**
```json
{
  "status": "alive",
  "node_id": "phone_01"
}
```

### 6.5 List Nodes
- **Endpoint:** `GET /api/v1/nodes`
- **Response:** Array of registered node objects.

### 6.6 Get Single Node
- **Endpoint:** `GET /api/v1/nodes/{node_id}`
- **Response (200 OK):** Full node object.
- **Response (404 Not Found):** `{"detail": "Node 'phone_01' not found"}`

### 6.7 Delete Node
- **Endpoint:** `DELETE /api/v1/nodes/{node_id}`
- **Response:**
```json
{
  "status": "removed",
  "node_id": "phone_01",
  "message": "Node 'phone_01' successfully removed from registry"
}
```

---

## 7. Automated Testing

Run the automated test suite with pytest:
```powershell
cd d:\MeshAI
.venv\Scripts\activate
pytest -v
```

All tests execute in memory/temporary databases without affecting persistent data in `data/meshai.db`.

---

## 8. Integration with Stage 2 (Android Worker Application)

In **Stage 2**, the Android Worker app will:
1. Discover the PC Orchestrator IP on the local Wi-Fi network (or use manual IP entry).
2. Gather native device hardware information via Android APIs:
   - Available RAM (`ActivityManager.MemoryInfo`)
   - CPU core count (`Runtime.getRuntime().availableProcessors()`)
   - Battery level (`BatteryManager`)
   - Supported local on-device models (e.g. ML Kit OCR, ONNX Runtime Vision, ExecuTorch).
3. Send an initial `POST /api/v1/nodes/register` to the orchestrator.
4. Launch an Android foreground service with a `WorkManager` periodic job posting `POST /api/v1/nodes/{node_id}/heartbeat` every 3 seconds.
5. In Step 3, the worker app will open an HTTP server on port `8080` to accept dispatched subtasks from the PC Orchestrator.
