"""Pydantic data models and schemas for MeshAI Orchestrator.

Defines schemas for nodes, registration requests, heartbeats, status responses,
and PC orchestrator information.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field, field_validator


class TaskStatus(str, Enum):
    """Enumeration of possible task statuses."""
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class JobStatus(str, Enum):
    """Enumeration of possible job statuses."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TaskCreate(BaseModel):
    """Payload to create a new task."""
    job_id: Optional[str] = Field(None, description="Optional job ID this task belongs to")
    task_type: str = Field(..., description="Type of task (e.g. PING)")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Task arguments/payload")
    required_capabilities: List[str] = Field(default_factory=list, description="Capabilities required to execute the task")
    priority: int = Field(default=1, description="Task priority (higher is more important)")

    @field_validator("required_capabilities")
    @classmethod
    def clean_capabilities(cls, v: List[str]) -> List[str]:
        """Normalize capability strings (lowercase, stripped, deduped)."""
        seen = set()
        cleaned = []
        for cap in v:
            c = cap.strip().lower()
            if c and c not in seen:
                seen.add(c)
                cleaned.append(c)
        return cleaned

    def model_post_init(self, __context: Any) -> None:
        """Automatically infer capabilities based on task_type to ensure backward compatibility."""
        t_type = self.task_type.upper()
        if t_type == "CALCULATE":
            if "calculate" not in self.required_capabilities:
                self.required_capabilities.append("calculate")
        if t_type == "PING":
            if "worker" not in self.required_capabilities:
                self.required_capabilities.append("worker")
        if t_type == "LLM_GENERATE":
            if "llm" not in self.required_capabilities:
                self.required_capabilities.append("llm")
            if "worker" not in self.required_capabilities:
                self.required_capabilities.append("worker")
            
            # Validate payload
            prompt = self.payload.get("prompt")
            if not prompt or not isinstance(prompt, str) or len(prompt.strip()) == 0:
                raise ValueError("LLM_GENERATE payload must contain a non-empty string 'prompt'")
            if len(prompt) > 8000:
                raise ValueError("LLM_GENERATE 'prompt' exceeds maximum length of 8000 characters")
            
            max_tokens = self.payload.get("max_tokens")
            if max_tokens is not None:
                if not isinstance(max_tokens, int) or max_tokens <= 0:
                    raise ValueError("LLM_GENERATE 'max_tokens' must be a positive integer")
                if max_tokens > 512:
                    raise ValueError("LLM_GENERATE 'max_tokens' cannot exceed 512")


class TaskResponse(BaseModel):
    """Full task domain model."""
    task_id: str
    job_id: Optional[str] = None
    task_type: str
    payload: Dict[str, Any]
    required_capabilities: List[str]
    priority: int
    status: TaskStatus
    assigned_node: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class JobCreate(BaseModel):
    """Payload to create a new job containing multiple tasks."""
    tasks: List[TaskCreate] = Field(..., description="List of tasks that make up this job")


class JobResponse(BaseModel):
    """Full job domain model."""
    job_id: str
    status: JobStatus
    created_at: datetime
    completed_at: Optional[datetime] = None
    tasks: List[TaskResponse] = Field(default_factory=list)


class TaskResultRequest(BaseModel):
    """Payload sent by worker to update task result."""
    node_id: str
    status: TaskStatus
    result: Optional[Any] = None
    error: Optional[str] = None


class NodeStatus(str, Enum):
    """Enumeration of possible node statuses."""
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class NodeRegisterRequest(BaseModel):
    """Payload sent by a worker node during initial registration or reconnection."""
    node_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Unique identifier for the worker node (e.g. phone_01)",
        examples=["phone_01"]
    )
    device_name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Human-readable device model / name",
        examples=["Galaxy S23"]
    )
    device_type: str = Field(
        default="android",
        description="Type of device (e.g. android, linux, windows)",
        examples=["android"]
    )
    operating_system: str = Field(
        default="Android",
        description="Operating system running on the worker",
        examples=["Android"]
    )
    ram_mb: int = Field(
        ...,
        gt=0,
        description="Total system RAM in Megabytes",
        examples=[8192]
    )
    cpu_cores: int = Field(
        ...,
        gt=0,
        description="Number of CPU cores",
        examples=[8]
    )
    battery_percent: Optional[int] = Field(
        default=None,
        ge=0,
        le=100,
        description="Battery percentage (0-100), optional if plugged in or desktop",
        examples=[82]
    )
    capabilities: List[str] = Field(
        default_factory=list,
        description="List of AI/compute capabilities supported by the node (e.g. ocr, vision, llm)",
        examples=[["ocr", "vision"]]
    )
    port: Optional[int] = Field(
        default=8080,
        ge=1,
        le=65535,
        description="Local port the worker node listens on for inbound tasks",
        examples=[8080]
    )
    
    # Phase 6: Hardware-Adaptive AI Extensions
    available_ram_mb: Optional[int] = Field(None, description="Available RAM at registration time")
    cpu_architecture: Optional[str] = Field(None, description="CPU Architecture (e.g. arm64-v8a)")
    ai_runtime: Optional[str] = Field(None, description="Name of the local AI inference engine")
    llm_available: Optional[bool] = Field(None, description="True if a local LLM is installed and ready")
    model_name: Optional[str] = Field(None, description="Name of the installed local model")
    model_size_mb: Optional[int] = Field(None, description="Size of the local model in MB")
    max_context_tokens: Optional[int] = Field(None, description="Maximum supported context size")
    max_output_tokens: Optional[int] = Field(None, description="Maximum supported output generation size")
    max_concurrent_inference: Optional[int] = Field(None, description="Number of parallel inferences allowed")

    @field_validator("capabilities")
    @classmethod
    def clean_capabilities(cls, v: List[str]) -> List[str]:
        """Normalize capability strings (lowercase, stripped, deduped)."""
        seen = set()
        cleaned = []
        for cap in v:
            c = cap.strip().lower()
            if c and c not in seen:
                seen.add(c)
                cleaned.append(c)
        return cleaned


class HeartbeatRequest(BaseModel):
    """Payload sent periodically by an active worker node."""
    battery_percent: Optional[int] = Field(
        default=None,
        ge=0,
        le=100,
        description="Current battery level percentage",
        examples=[78]
    )


class NodeResponse(BaseModel):
    """Full node domain model returned by individual node endpoint."""
    node_id: str
    device_name: str
    device_type: str
    operating_system: str
    ram_mb: int
    cpu_cores: int
    battery_percent: Optional[int] = None
    capabilities: List[str]
    ip_address: Optional[str] = None
    port: Optional[int] = None
    registered_at: datetime
    last_seen: datetime
    status: NodeStatus
    
    # Phase 6: Hardware-Adaptive AI Extensions
    available_ram_mb: Optional[int] = None
    cpu_architecture: Optional[str] = None
    ai_runtime: Optional[str] = None
    llm_available: Optional[bool] = None
    model_name: Optional[str] = None
    model_size_mb: Optional[int] = None
    max_context_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    max_concurrent_inference: Optional[int] = None


class NodeSummaryResponse(BaseModel):
    """Compact summary of a node returned in node listings."""
    node_id: str
    device_name: str
    status: NodeStatus
    ram_mb: int
    cpu_cores: int
    battery_percent: Optional[int] = None
    capabilities: List[str]
    ip_address: Optional[str] = None
    port: Optional[int] = None
    last_seen: datetime
    
    # Phase 6: Quick AI summary
    llm_available: Optional[bool] = None


class NodeRegisterResponse(BaseModel):
    """Response returned upon node registration."""
    status: str = Field(..., description="Action taken: 'registered' or 'updated'")
    node_id: str
    message: str


class HeartbeatResponse(BaseModel):
    """Response returned upon successful heartbeat reception."""
    status: str = "alive"
    node_id: str


class SystemStatusResponse(BaseModel):
    """System status and node count metrics."""
    system: str = "MeshAI"
    status: str = "running"
    version: str = "0.1.0"
    nodes_total: int
    nodes_online: int
    nodes_offline: int


class RootResponse(BaseModel):
    """Root endpoint response."""
    system: str = "MeshAI Orchestrator"
    version: str = "0.1.0"
    status: str = "running"


class OrchestratorInfoResponse(BaseModel):
    """Information about the host PC running the MeshAI Orchestrator."""
    hostname: str
    operating_system: str
    cpu_cores_physical: int
    cpu_cores_logical: int
    ram_total_mb: int
    ram_available_mb: int
    ram_used_percent: float
    local_ip_addresses: List[str]
