import logging
import threading
from typing import Optional

from orchestrator.models import TaskCreate, TaskResponse, TaskStatus, NodeStatus
from orchestrator.node_manager import node_manager
from orchestrator.task_manager import create_task, update_task_status, get_active_load, get_task

logger = logging.getLogger("meshai.task_scheduler")

_scheduler_lock = threading.Lock()


def schedule_task(task_in: TaskCreate) -> TaskResponse:
    """Creates a task and attempts to assign it to an available worker."""
    task = create_task(task_in)
    
    with _scheduler_lock:
        logger.info("[SCHEDULER] Evaluating workers")
        
        nodes = node_manager.get_all_nodes()
        online_nodes = [n for n in nodes if n.status == NodeStatus.ONLINE]
        
        if not online_nodes:
            logger.warning("[SCHEDULER] No online workers available")
            return task
            
        # Match capabilities
        suitable_nodes = []
        for node in online_nodes:
            if all(cap in node.capabilities for cap in task_in.required_capabilities):
                suitable_nodes.append(node)
                
        if not suitable_nodes:
            logger.warning("[SCHEDULER] No workers with required capabilities")
            return task
            
        # Evaluate load and build candidate list
        candidates = []
        for node in suitable_nodes:
            active_tasks = get_active_load(node.node_id)
            logger.info(
                f"[SCHEDULER] Worker {node.node_id}:\n"
                f"active_tasks={active_tasks}\n"
                f"ram_mb={node.ram_mb}\n"
                f"capabilities={node.capabilities}"
            )
            candidates.append({
                "node": node,
                "active_tasks": active_tasks
            })
            
        # Sort candidates:
        # 1. active_tasks ascending (lower load is better)
        # 2. ram_mb descending (more RAM is better)
        # 3. node_id ascending (deterministic tie-breaker)
        candidates.sort(
            key=lambda c: (
                c["active_tasks"],
                -c["node"].ram_mb,
                c["node"].node_id
            )
        )
        
        selected_node = candidates[0]["node"]
        logger.info(f"[SCHEDULER] Selected worker {selected_node.node_id}")
        
        update_task_status(task.task_id, TaskStatus.ASSIGNED, selected_node.node_id)
        
    return get_task(task.task_id)
