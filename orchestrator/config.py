"""Configuration module for MeshAI Orchestrator.

Provides centralized configuration variables with environment variable override
support and default fallback values.
"""

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass
class Settings:
    """MeshAI Orchestrator configuration settings."""

    # Server binding
    HOST: str = os.getenv("MESHAI_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("MESHAI_PORT", "8000"))

    # Health monitoring and heartbeats
    HEARTBEAT_INTERVAL_SECONDS: int = int(
        os.getenv("MESHAI_HEARTBEAT_INTERVAL", "3")
    )
    NODE_TIMEOUT_SECONDS: int = int(
        os.getenv("MESHAI_NODE_TIMEOUT", "10")
    )

    # Database storage path
    # Defaults to data/meshai.db relative to the project root (parent of orchestrator)
    DATABASE_PATH: str = os.getenv(
        "MESHAI_DATABASE_PATH",
        str(
            (Path(__file__).resolve().parent.parent / "data" / "meshai.db").resolve()
        ),
    )

    # Application metadata
    SYSTEM_NAME: str = "MeshAI Orchestrator"
    VERSION: str = "0.1.0"


# Singleton instance for application-wide use
settings = Settings()
