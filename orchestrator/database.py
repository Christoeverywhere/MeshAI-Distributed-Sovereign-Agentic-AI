"""SQLite database initialization and connection management for MeshAI Orchestrator.

Provides persistent storage for node registry without requiring any external database server.
"""

from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import sqlite3
from typing import Generator
from orchestrator.config import settings

logger = logging.getLogger("meshai.database")


def get_db_path() -> str:
    """Return the absolute path to the SQLite database file."""
    db_path = Path(settings.DATABASE_PATH).resolve()
    # Ensure directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return str(db_path)


@contextmanager
def get_db(db_path: str | None = None) -> Generator[sqlite3.Connection, None, None]:
    """Provide a transactional SQLite database connection with row factory."""
    path = db_path or get_db_path()
    conn = sqlite3.connect(path, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str | None = None) -> None:
    """Initialize the SQLite database schema and tables if they do not exist."""
    path = db_path or get_db_path()
    logger.info(f"Initializing database at {path}")

    with get_db(path) as conn:
        # Enable Write-Ahead Logging for better concurrent performance
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")

        # Create nodes table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS nodes (
                node_id TEXT PRIMARY KEY,
                device_name TEXT NOT NULL,
                device_type TEXT NOT NULL,
                operating_system TEXT NOT NULL,
                ram_mb INTEGER NOT NULL,
                cpu_cores INTEGER NOT NULL,
                battery_percent INTEGER,
                capabilities TEXT NOT NULL,
                ip_address TEXT,
                port INTEGER,
                registered_at TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                status TEXT NOT NULL,
                ai_metadata TEXT
            );
            """
        )
        
        try:
            conn.execute("ALTER TABLE nodes ADD COLUMN ai_metadata TEXT;")
        except sqlite3.OperationalError:
            pass

        # Create indexes for fast status queries and timeout sweeps
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_nodes_status ON nodes(status);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_nodes_last_seen ON nodes(last_seen);"
        )

        # Create jobs table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );
            """
        )

        # Create tasks table
        # Adding job_id optionally
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                job_id TEXT,
                task_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                required_capabilities TEXT NOT NULL,
                priority INTEGER NOT NULL,
                status TEXT NOT NULL,
                assigned_node TEXT,
                result TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
            );
            """
        )
        
        # Add job_id column if tasks table already existed without it (simple migration)
        try:
            conn.execute("ALTER TABLE tasks ADD COLUMN job_id TEXT REFERENCES jobs(job_id) ON DELETE CASCADE;")
        except sqlite3.OperationalError:
            pass # Column likely exists already

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_assigned_node ON tasks(assigned_node);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_job_id ON tasks(job_id);"
        )

    logger.info("Database initialized successfully")
