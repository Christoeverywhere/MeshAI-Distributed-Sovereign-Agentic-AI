import json
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from orchestrator.database import get_db
from orchestrator.models import TaskCreate, TaskResponse, TaskStatus, TaskResultRequest

logger = logging.getLogger("meshai.task_manager")


def _row_to_task(row) -> TaskResponse:
    return TaskResponse(
        task_id=row["task_id"],
        job_id=row["job_id"],
        task_type=row["task_type"],
        payload=json.loads(row["payload"]),
        required_capabilities=json.loads(row["required_capabilities"]),
        priority=row["priority"],
        status=TaskStatus(row["status"]),
        assigned_node=row["assigned_node"],
        result=json.loads(row["result"]) if row["result"] else None,
        error=row["error"],
        created_at=datetime.fromisoformat(row["created_at"]),
        started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
        completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None
    )


def create_task(task_in: TaskCreate) -> TaskResponse:
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    task = TaskResponse(
        task_id=task_id,
        job_id=task_in.job_id,
        task_type=task_in.task_type,
        payload=task_in.payload,
        required_capabilities=task_in.required_capabilities,
        priority=task_in.priority,
        status=TaskStatus.PENDING,
        created_at=now
    )

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO tasks (
                task_id, job_id, task_type, payload, required_capabilities, priority,
                status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.task_id,
                task.job_id,
                task.task_type,
                json.dumps(task.payload),
                json.dumps(task.required_capabilities),
                task.priority,
                task.status.value,
                task.created_at.isoformat()
            )
        )
    logger.info(f"[TASK] Created task {task_id}")
    return task


def get_task(task_id: str) -> Optional[TaskResponse]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if not row:
            return None
        return _row_to_task(row)


def list_tasks() -> List[TaskResponse]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
        return [_row_to_task(row) for row in rows]


def get_tasks_for_node(node_id: str, status: Optional[TaskStatus] = None) -> List[TaskResponse]:
    with get_db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE assigned_node = ? AND status = ? ORDER BY priority DESC, created_at ASC",
                (node_id, status.value)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE assigned_node = ? ORDER BY priority DESC, created_at ASC",
                (node_id,)
            ).fetchall()
        return [_row_to_task(row) for row in rows]


def get_active_load(node_id: str) -> int:
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE assigned_node = ? AND status IN (?, ?)",
            (node_id, TaskStatus.ASSIGNED.value, TaskStatus.RUNNING.value)
        ).fetchone()
        return row[0] if row else 0


def update_task_status(task_id: str, status: TaskStatus, assigned_node: Optional[str] = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        if status == TaskStatus.ASSIGNED:
            conn.execute(
                "UPDATE tasks SET status = ?, assigned_node = ? WHERE task_id = ?",
                (status.value, assigned_node, task_id)
            )
            logger.info(f"[TASK] Assigned {task_id} -> {assigned_node}")
        elif status == TaskStatus.RUNNING:
            conn.execute(
                "UPDATE tasks SET status = ?, started_at = ? WHERE task_id = ?",
                (status.value, now, task_id)
            )
        elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            conn.execute(
                "UPDATE tasks SET status = ?, completed_at = ? WHERE task_id = ?",
                (status.value, now, task_id)
            )
            logger.info(f"[TASK] {task_id} {status.value}")


def process_task_result(task_id: str, result_req: TaskResultRequest) -> Optional[TaskResponse]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if not row:
            return None
        
        now = datetime.now(timezone.utc).isoformat()
        res_str = json.dumps(result_req.result) if result_req.result is not None else None
        
        conn.execute(
            """
            UPDATE tasks 
            SET status = ?, result = ?, error = ?, completed_at = ?
            WHERE task_id = ?
            """,
            (result_req.status.value, res_str, result_req.error, now, task_id)
        )
        logger.info(f"[TASK] {task_id} {result_req.status.value}")
    
    return get_task(task_id)


from orchestrator.models import JobCreate, JobResponse, JobStatus

def create_job(job_in: JobCreate) -> JobResponse:
    job_id = f"job_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO jobs (job_id, status, created_at)
            VALUES (?, ?, ?)
            """,
            (job_id, JobStatus.PENDING.value, now.isoformat())
        )
    
    logger.info(f"[JOB] Created job {job_id} with {len(job_in.tasks)} tasks")
    
    # Delegate to task scheduler to insert tasks
    from orchestrator.task_scheduler import schedule_task
    tasks = []
    for task_in in job_in.tasks:
        task_in.job_id = job_id
        tasks.append(schedule_task(task_in))
        
    return get_job(job_id)

def get_job(job_id: str) -> Optional[JobResponse]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            return None
        
        # Get tasks for job
        task_rows = conn.execute("SELECT * FROM tasks WHERE job_id = ? ORDER BY created_at ASC", (job_id,)).fetchall()
        tasks = [_row_to_task(r) for r in task_rows]
        
        status = JobStatus(row["status"])
        
        # Auto-compute job status from tasks if pending/running
        if tasks and status not in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            all_completed = all(t.status == TaskStatus.COMPLETED for t in tasks)
            any_failed = any(t.status == TaskStatus.FAILED for t in tasks)
            any_running = any(t.status in (TaskStatus.RUNNING, TaskStatus.ASSIGNED) for t in tasks)
            
            new_status = status
            if any_failed:
                new_status = JobStatus.FAILED
            elif all_completed:
                new_status = JobStatus.COMPLETED
            elif any_running:
                new_status = JobStatus.RUNNING
                
            if new_status != status:
                status = new_status
                now = datetime.now(timezone.utc).isoformat()
                if new_status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                    conn.execute("UPDATE jobs SET status = ?, completed_at = ? WHERE job_id = ?", (new_status.value, now, job_id))
                else:
                    conn.execute("UPDATE jobs SET status = ? WHERE job_id = ?", (new_status.value, job_id))
                    
        return JobResponse(
            job_id=row["job_id"],
            status=status,
            created_at=datetime.fromisoformat(row["created_at"]),
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            tasks=tasks
        )

def list_jobs() -> List[JobResponse]:
    with get_db() as conn:
        rows = conn.execute("SELECT job_id FROM jobs ORDER BY created_at DESC").fetchall()
        # Call get_job for each to recompute dynamic status
        return [get_job(r["job_id"]) for r in rows if get_job(r["job_id"])]

def cancel_job(job_id: str) -> Optional[JobResponse]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            return None
            
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("UPDATE jobs SET status = ?, completed_at = ? WHERE job_id = ?", (JobStatus.CANCELLED.value, now, job_id))
        
        # Cancel all pending/assigned/running tasks
        conn.execute(
            """
            UPDATE tasks SET status = ?, completed_at = ? 
            WHERE job_id = ? AND status IN (?, ?, ?)
            """,
            (TaskStatus.CANCELLED.value, now, job_id, TaskStatus.PENDING.value, TaskStatus.ASSIGNED.value, TaskStatus.RUNNING.value)
        )
        logger.info(f"[JOB] Cancelled job {job_id}")
        
    return get_job(job_id)
