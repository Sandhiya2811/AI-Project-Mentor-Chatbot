from __future__ import annotations

from database import repository as repo


def record_attempt(task_id: int) -> int:
    return repo.increment_attempts(task_id)


def mark_passed(project_id: int, task: dict):
    """Marks the task passed, unlocks the next one. Returns (progress, next_task | None)."""
    repo.set_task_status(task["id"], "passed")
    tasks = repo.list_tasks(project_id)
    nxt = next((t for t in tasks if t["position"] > task["position"] and t["status"] == "locked"), None)
    if nxt:
        repo.set_task_status(nxt["id"], "active")
        nxt["status"] = "active"
    return repo.refresh_progress(project_id), nxt
