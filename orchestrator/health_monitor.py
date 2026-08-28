"""Health Monitor for MeshAI Orchestrator.

Runs an asynchronous background task that periodically audits registered worker nodes
and marks inactive nodes as OFFLINE when heartbeat timeouts are exceeded.
"""

import asyncio
import logging
from typing import Optional
from orchestrator.config import settings
from orchestrator.node_manager import node_manager

logger = logging.getLogger("meshai.health_monitor")


class HealthMonitor:
    """Background service monitoring worker node heartbeats."""

    def __init__(
        self,
        interval_seconds: Optional[int] = None,
        timeout_seconds: Optional[int] = None,
    ):
        self.interval_seconds = interval_seconds or settings.HEARTBEAT_INTERVAL_SECONDS
        self.timeout_seconds = timeout_seconds or settings.NODE_TIMEOUT_SECONDS
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def _run_loop(self) -> None:
        """Main periodic audit loop."""
        logger.info(
            f"Health monitor loop started (check interval: {self.interval_seconds}s, "
            f"timeout threshold: {self.timeout_seconds}s)"
        )
        while self._running:
            try:
                # Audit and update expired nodes
                node_manager.check_and_update_offline_nodes(self.timeout_seconds)
            except Exception as e:
                logger.error(f"Error during health check sweep: {e}", exc_info=True)

            try:
                await asyncio.sleep(self.interval_seconds)
            except asyncio.CancelledError:
                break

        logger.info("Health monitor loop stopped")

    def start(self) -> None:
        """Start the health monitoring background task."""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Gracefully stop the health monitor."""
        if self._running:
            self._running = False
            if self._task:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
                self._task = None


# Singleton instance
health_monitor = HealthMonitor()
