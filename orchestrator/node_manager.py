"""Node Manager for MeshAI Orchestrator.

Handles registration, heartbeat management, status determination, persistence,
and retrieval of worker nodes.
"""

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from orchestrator.database import get_db
from orchestrator.models import (
    NodeRegisterRequest,
    NodeResponse,
    NodeStatus,
    NodeSummaryResponse,
)

logger = logging.getLogger("meshai.orchestrator")


class NodeManager:
    """Thread-safe manager for all worker node operations and database state."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    @staticmethod
    def _row_to_node_response(row: Any) -> NodeResponse:
        """Convert a database row to a Pydantic NodeResponse model."""
        capabilities_raw = row["capabilities"]
        if isinstance(capabilities_raw, str):
            try:
                capabilities = json.loads(capabilities_raw)
            except json.JSONDecodeError:
                capabilities = [capabilities_raw]
        elif isinstance(capabilities_raw, list):
            capabilities = capabilities_raw
        else:
            capabilities = []

        ai_meta = {}
        if "ai_metadata" in row.keys() and row["ai_metadata"]:
            try:
                ai_meta = json.loads(row["ai_metadata"])
            except json.JSONDecodeError:
                pass

        return NodeResponse(
            node_id=row["node_id"],
            device_name=row["device_name"],
            device_type=row["device_type"],
            operating_system=row["operating_system"],
            ram_mb=row["ram_mb"],
            cpu_cores=row["cpu_cores"],
            battery_percent=row["battery_percent"],
            capabilities=capabilities,
            ip_address=row["ip_address"],
            port=row["port"],
            registered_at=datetime.fromisoformat(row["registered_at"]),
            last_seen=datetime.fromisoformat(row["last_seen"]),
            status=NodeStatus(row["status"]),
            available_ram_mb=ai_meta.get("available_ram_mb"),
            cpu_architecture=ai_meta.get("cpu_architecture"),
            ai_runtime=ai_meta.get("ai_runtime"),
            llm_available=ai_meta.get("llm_available"),
            model_name=ai_meta.get("model_name"),
            model_size_mb=ai_meta.get("model_size_mb"),
            max_context_tokens=ai_meta.get("max_context_tokens"),
            max_output_tokens=ai_meta.get("max_output_tokens"),
            max_concurrent_inference=ai_meta.get("max_concurrent_inference")
        )

    def register_or_update_node(
        self,
        request: NodeRegisterRequest,
        client_ip: Optional[str] = None,
    ) -> Tuple[bool, NodeResponse]:
        """Register a new worker node or update an existing one.

        Returns:
            Tuple of (is_new_registration: bool, node_response: NodeResponse)
        """
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        capabilities_json = json.dumps(request.capabilities)
        
        ai_meta = {
            "available_ram_mb": request.available_ram_mb,
            "cpu_architecture": request.cpu_architecture,
            "ai_runtime": request.ai_runtime,
            "llm_available": request.llm_available,
            "model_name": request.model_name,
            "model_size_mb": request.model_size_mb,
            "max_context_tokens": request.max_context_tokens,
            "max_output_tokens": request.max_output_tokens,
            "max_concurrent_inference": request.max_concurrent_inference
        }
        # Remove None values
        ai_meta = {k: v for k, v in ai_meta.items() if v is not None}
        ai_metadata_json = json.dumps(ai_meta) if ai_meta else None

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM nodes WHERE node_id = ?", (request.node_id,)
            )
            existing = cursor.fetchone()

            if existing:
                # Existing node reconnecting or updating specs
                was_offline = existing["status"] == NodeStatus.OFFLINE.value
                cursor.execute(
                    """
                    UPDATE nodes
                    SET device_name = ?,
                        device_type = ?,
                        operating_system = ?,
                        ram_mb = ?,
                        cpu_cores = ?,
                        battery_percent = COALESCE(?, battery_percent),
                        capabilities = ?,
                        ip_address = ?,
                        port = ?,
                        last_seen = ?,
                        status = ?,
                        ai_metadata = ?
                    WHERE node_id = ?
                    """,
                    (
                        request.device_name,
                        request.device_type,
                        request.operating_system,
                        request.ram_mb,
                        request.cpu_cores,
                        request.battery_percent,
                        capabilities_json,
                        client_ip or existing["ip_address"],
                        request.port or existing["port"],
                        now_iso,
                        NodeStatus.ONLINE.value,
                        ai_metadata_json,
                        request.node_id,
                    ),
                )
                if was_offline:
                    logger.info(f"Node reconnected: {request.node_id}")
                else:
                    logger.info(f"Node updated: {request.node_id}")
                is_new = False
            else:
                # New node registration
                cursor.execute(
                    """
                    INSERT INTO nodes (
                        node_id, device_name, device_type, operating_system,
                        ram_mb, cpu_cores, battery_percent, capabilities,
                        ip_address, port, registered_at, last_seen, status, ai_metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request.node_id,
                        request.device_name,
                        request.device_type,
                        request.operating_system,
                        request.ram_mb,
                        request.cpu_cores,
                        request.battery_percent,
                        capabilities_json,
                        client_ip,
                        request.port,
                        now_iso,
                        now_iso,
                        NodeStatus.ONLINE.value,
                        ai_metadata_json,
                    ),
                )
                logger.info(f"Node registered: {request.node_id}")
                is_new = True

            cursor.execute(
                "SELECT * FROM nodes WHERE node_id = ?", (request.node_id,)
            )
            updated_row = cursor.fetchone()
            return is_new, self._row_to_node_response(updated_row)

    def record_heartbeat(
        self,
        node_id: str,
        battery_percent: Optional[int] = None,
        client_ip: Optional[str] = None,
    ) -> Optional[NodeResponse]:
        """Process a heartbeat from a worker node.

        Updates last_seen timestamp, battery level (if provided), and marks the node ONLINE.
        Returns the updated NodeResponse, or None if the node is not found.
        """
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,))
            existing = cursor.fetchone()

            if not existing:
                return None

            was_offline = existing["status"] == NodeStatus.OFFLINE.value

            if battery_percent is not None:
                cursor.execute(
                    """
                    UPDATE nodes
                    SET last_seen = ?,
                        battery_percent = ?,
                        ip_address = COALESCE(?, ip_address),
                        status = ?
                    WHERE node_id = ?
                    """,
                    (
                        now_iso,
                        battery_percent,
                        client_ip,
                        NodeStatus.ONLINE.value,
                        node_id,
                    ),
                )
            else:
                cursor.execute(
                    """
                    UPDATE nodes
                    SET last_seen = ?,
                        ip_address = COALESCE(?, ip_address),
                        status = ?
                    WHERE node_id = ?
                    """,
                    (
                        now_iso,
                        client_ip,
                        NodeStatus.ONLINE.value,
                        node_id,
                    ),
                )

            if was_offline:
                logger.info(f"Node reconnected: {node_id}")
            else:
                logger.info(f"Heartbeat received: {node_id}")

            cursor.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,))
            updated_row = cursor.fetchone()
            return self._row_to_node_response(updated_row)

    def get_node(self, node_id: str) -> Optional[NodeResponse]:
        """Retrieve complete information for a specific node by ID."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_node_response(row)

    def get_all_nodes(self) -> List[NodeResponse]:
        """Retrieve all known nodes from the registry."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM nodes ORDER BY registered_at ASC")
            rows = cursor.fetchall()
            return [self._row_to_node_response(row) for row in rows]

    def remove_node(self, node_id: str) -> bool:
        """Remove a node from the registry database.

        Returns True if the node existed and was deleted, False otherwise.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM nodes WHERE node_id = ?", (node_id,))
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"Node removed: {node_id}")
            return deleted

    def check_and_update_offline_nodes(self, timeout_seconds: int) -> List[str]:
        """Identify ONLINE nodes that have not reported within timeout_seconds and set to OFFLINE.

        Returns:
            List of node_ids that transitioned from ONLINE to OFFLINE.
        """
        now = datetime.now(timezone.utc)
        marked_offline: List[str] = []

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            # Find all nodes currently marked ONLINE
            cursor.execute(
                "SELECT node_id, last_seen FROM nodes WHERE status = ?",
                (NodeStatus.ONLINE.value,),
            )
            online_nodes = cursor.fetchall()

            for row in online_nodes:
                node_id = row["node_id"]
                last_seen_dt = datetime.fromisoformat(row["last_seen"])
                # Handle naive vs timezone-aware timestamps safely
                if last_seen_dt.tzinfo is None:
                    last_seen_dt = last_seen_dt.replace(tzinfo=timezone.utc)

                elapsed = (now - last_seen_dt).total_seconds()
                if elapsed > timeout_seconds:
                    cursor.execute(
                        "UPDATE nodes SET status = ? WHERE node_id = ?",
                        (NodeStatus.OFFLINE.value, node_id),
                    )
                    
                    # Fail tasks assigned to this disconnected node
                    from orchestrator.models import TaskStatus
                    now_iso = now.isoformat()
                    cursor.execute(
                        """
                        UPDATE tasks SET status = ?, error = ?, completed_at = ?
                        WHERE assigned_node = ? AND status IN (?, ?)
                        """,
                        (TaskStatus.FAILED.value, "Worker disconnected", now_iso, node_id, TaskStatus.ASSIGNED.value, TaskStatus.RUNNING.value)
                    )
                    
                    marked_offline.append(node_id)
                    logger.warning(f"Node offline: {node_id}")

        return marked_offline

    def get_status_counts(self) -> Dict[str, int]:
        """Return counts of total, online, and offline nodes."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as total FROM nodes")
            total = cursor.fetchone()["total"]

            cursor.execute(
                "SELECT COUNT(*) as online FROM nodes WHERE status = ?",
                (NodeStatus.ONLINE.value,),
            )
            online = cursor.fetchone()["online"]

            cursor.execute(
                "SELECT COUNT(*) as offline FROM nodes WHERE status = ?",
                (NodeStatus.OFFLINE.value,),
            )
            offline = cursor.fetchone()["offline"]

            return {
                "nodes_total": total,
                "nodes_online": online,
                "nodes_offline": offline,
            }


# Singleton manager instance using default settings
node_manager = NodeManager()
