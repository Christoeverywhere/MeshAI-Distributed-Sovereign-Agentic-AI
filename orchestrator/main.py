"""MeshAI Orchestrator - Main FastAPI Application.

Provides REST API endpoints for worker node registration, heartbeat tracking,
health monitoring, cluster status, and host PC hardware introspection.
"""

from contextlib import asynccontextmanager
import logging
import platform
import socket
import sys
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request, status
import psutil

from orchestrator.config import settings
from orchestrator.database import init_db
from orchestrator.health_monitor import health_monitor
from orchestrator.models import (
    HeartbeatRequest,
    HeartbeatResponse,
    NodeRegisterRequest,
    NodeRegisterResponse,
    NodeResponse,
    OrchestratorInfoResponse,
    RootResponse,
    SystemStatusResponse,
    TaskCreate,
    TaskResponse,
    TaskResultRequest,
    TaskStatus
)
from orchestrator.node_manager import node_manager
from orchestrator.task_manager import list_tasks, get_task, get_tasks_for_node, process_task_result, update_task_status
from orchestrator.task_scheduler import schedule_task

# Configure logging format to match MeshAI specifications
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("meshai.orchestrator")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager to handle DB initialization and background tasks."""
    # Startup
    init_db()
    health_monitor.start()
    logger.info("MeshAI Orchestrator started")
    yield
    # Shutdown
    await health_monitor.stop()
    logger.info("MeshAI Orchestrator stopped")


app = FastAPI(
    title="MeshAI Orchestrator",
    description=(
        "Local, air-gapped AI orchestrator coordinating trusted smartphones, laptops, "
        "and GPU machines across local Wi-Fi/LAN networks."
    ),
    version=settings.VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


def _get_local_ip_addresses() -> List[str]:
    """Discover local non-loopback IPv4 addresses of the host machine."""
    ip_list = []
    try:
        # Get all network interface addresses using psutil
        interfaces = psutil.net_if_addrs()
        for iface_name, addresses in interfaces.items():
            for addr in addresses:
                if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                    ip_list.append(addr.address)
    except Exception:
        pass

    # Fallback to standard socket connection technique if empty
    if not ip_list:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            primary_ip = s.getsockname()[0]
            s.close()
            if primary_ip and not primary_ip.startswith("127."):
                ip_list.append(primary_ip)
        except Exception:
            ip_list.append("127.0.0.1")

    return list(dict.fromkeys(ip_list))


@app.get(
    "/",
    response_model=RootResponse,
    summary="Root Service Information",
    tags=["General"],
)
async def root():
    """Return basic orchestrator service identity and operational state."""
    return RootResponse(
        system=settings.SYSTEM_NAME,
        version=settings.VERSION,
        status="running",
    )


@app.get(
    "/api/v1/status",
    response_model=SystemStatusResponse,
    summary="Orchestrator Cluster Status",
    tags=["Cluster Status"],
)
async def get_system_status():
    """Return real-time cluster metrics including total, online, and offline node counts."""
    metrics = node_manager.get_status_counts()
    return SystemStatusResponse(
        system="MeshAI",
        status="running",
        version=settings.VERSION,
        nodes_total=metrics["nodes_total"],
        nodes_online=metrics["nodes_online"],
        nodes_offline=metrics["nodes_offline"],
    )


@app.get(
    "/api/v1/orchestrator/info",
    response_model=OrchestratorInfoResponse,
    summary="PC Self Information",
    tags=["Host Diagnostics"],
)
async def get_orchestrator_info():
    """Return hardware diagnostics and local network addresses for the host PC."""
    vm = psutil.virtual_memory()
    total_ram_mb = int(vm.total / (1024 * 1024))
    available_ram_mb = int(vm.available / (1024 * 1024))
    ram_used_percent = float(vm.percent)

    physical_cores = psutil.cpu_count(logical=False) or psutil.cpu_count() or 1
    logical_cores = psutil.cpu_count(logical=True) or physical_cores

    return OrchestratorInfoResponse(
        hostname=socket.gethostname(),
        operating_system=f"{platform.system()} {platform.release()} ({platform.version()})",
        cpu_cores_physical=physical_cores,
        cpu_cores_logical=logical_cores,
        ram_total_mb=total_ram_mb,
        ram_available_mb=available_ram_mb,
        ram_used_percent=ram_used_percent,
        local_ip_addresses=_get_local_ip_addresses(),
    )


@app.post(
    "/api/v1/nodes/register",
    response_model=NodeRegisterResponse,
    status_code=status.HTTP_200_OK,
    summary="Register or Update Worker Node",
    tags=["Node Management"],
)
async def register_node(request_data: NodeRegisterRequest, request: Request):
    """Register an Android phone or worker device with MeshAI, or update an existing node record.

    The client IP address is automatically extracted from the incoming network connection.
    """
    client_ip = request.client.host if request.client else None

    is_new, node = node_manager.register_or_update_node(
        request_data, client_ip=client_ip
    )

    if is_new:
        return NodeRegisterResponse(
            status="registered",
            node_id=node.node_id,
            message="Node successfully registered with MeshAI",
        )
    else:
        return NodeRegisterResponse(
            status="updated",
            node_id=node.node_id,
            message="Node successfully updated in MeshAI",
        )


@app.post(
    "/api/v1/nodes/{node_id}/heartbeat",
    response_model=HeartbeatResponse,
    summary="Send Worker Node Heartbeat",
    tags=["Node Management"],
)
async def node_heartbeat(
    node_id: str,
    heartbeat_data: Optional[HeartbeatRequest] = None,
    request: Request = None,
):
    """Record a periodic heartbeat for a registered node, updating its last_seen timestamp and battery."""
    client_ip = request.client.host if request and request.client else None
    battery = heartbeat_data.battery_percent if heartbeat_data else None

    updated_node = node_manager.record_heartbeat(
        node_id=node_id,
        battery_percent=battery,
        client_ip=client_ip,
    )

    if not updated_node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node '{node_id}' is not registered with MeshAI",
        )

    return HeartbeatResponse(status="alive", node_id=node_id)


@app.get(
    "/api/v1/nodes",
    response_model=List[NodeResponse],
    summary="List All Worker Nodes",
    tags=["Node Management"],
)
async def list_nodes():
    """Retrieve all known worker nodes and their current computed status."""
    return node_manager.get_all_nodes()


@app.get(
    "/api/v1/nodes/{node_id}",
    response_model=NodeResponse,
    summary="Get Specific Worker Node",
    tags=["Node Management"],
)
async def get_node(node_id: str):
    """Retrieve full hardware and status details for a single worker node."""
    node = node_manager.get_node(node_id)
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node '{node_id}' not found",
        )
    return node


@app.delete(
    "/api/v1/nodes/{node_id}",
    summary="Remove Worker Node",
    tags=["Node Management"],
)
async def remove_node(node_id: str):
    """Remove a worker node from the registry."""
    deleted = node_manager.remove_node(node_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node '{node_id}' not found",
        )
    return {
        "status": "removed",
        "node_id": node_id,
        "message": f"Node '{node_id}' successfully removed from registry",
    }


@app.post(
    "/api/v1/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new task",
    tags=["Task Management"],
)
async def create_new_task(task_in: TaskCreate):
    """Create a new task and attempt to schedule it to a suitable worker node."""
    return schedule_task(task_in)


@app.get(
    "/api/v1/tasks",
    response_model=List[TaskResponse],
    summary="List all tasks",
    tags=["Task Management"],
)
async def get_all_tasks():
    """Retrieve all tasks."""
    return list_tasks()


@app.get(
    "/api/v1/tasks/{task_id}",
    response_model=TaskResponse,
    summary="Get a specific task",
    tags=["Task Management"],
)
async def get_task_by_id(task_id: str):
    """Retrieve full details for a single task."""
    task = get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found",
        )
    return task


@app.get(
    "/api/v1/nodes/{node_id}/tasks",
    response_model=Optional[TaskResponse],
    summary="Poll for assigned tasks",
    tags=["Task Management"],
)
async def poll_tasks(node_id: str):
    """Worker node polls for assigned tasks. Returns the highest priority pending task."""
    tasks = get_tasks_for_node(node_id, status=TaskStatus.ASSIGNED)
    if not tasks:
        return None
        
    task = tasks[0]
    # Mark as running when polled
    update_task_status(task.task_id, TaskStatus.RUNNING)
    logger.info(f"[WORKER] Received task {task.task_id} (Node: {node_id})")
    return get_task(task.task_id)


@app.post(
    "/api/v1/tasks/{task_id}/result",
    response_model=TaskResponse,
    summary="Submit task result",
    tags=["Task Management"],
)
async def submit_task_result(task_id: str, result_req: TaskResultRequest):
    """Worker node submits the result of a task."""
    task = process_task_result(task_id, result_req)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found",
        )
    return task


from orchestrator.models import JobCreate, JobResponse
from orchestrator.task_manager import create_job, get_job, list_jobs, cancel_job

@app.post(
    "/api/v1/jobs",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new job (batch of tasks)",
    tags=["Job Management"],
)
async def create_new_job(job_in: JobCreate):
    """Create a new job containing multiple tasks and schedule them."""
    return create_job(job_in)


@app.get(
    "/api/v1/jobs",
    response_model=List[JobResponse],
    summary="List all jobs",
    tags=["Job Management"],
)
async def get_all_jobs():
    """Retrieve all jobs."""
    return list_jobs()


@app.get(
    "/api/v1/jobs/{job_id}",
    response_model=JobResponse,
    summary="Get a specific job",
    tags=["Job Management"],
)
async def get_job_by_id(job_id: str):
    """Retrieve full details for a single job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )
    return job


@app.get(
    "/api/v1/jobs/{job_id}/tasks",
    response_model=List[TaskResponse],
    summary="Get all tasks for a specific job",
    tags=["Job Management"],
)
async def get_tasks_for_job(job_id: str):
    """Retrieve all tasks associated with a job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )
    return job.tasks


@app.post(
    "/api/v1/jobs/{job_id}/cancel",
    response_model=JobResponse,
    summary="Cancel a job",
    tags=["Job Management"],
)
async def cancel_job_by_id(job_id: str):
    """Cancel a job and all its pending/running tasks."""
    job = cancel_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )
    return job


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "orchestrator.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
    )
