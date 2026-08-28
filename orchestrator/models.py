"""Pydantic data models and schemas for MeshAI Orchestrator.

Defines schemas for nodes, registration requests, heartbeats, status responses,
and PC orchestrator information.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


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
