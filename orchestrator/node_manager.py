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
                        status = ?
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
                        ip_address, port, registered_at, last_seen, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
