from __future__ import annotations

from database import repository as repo


def active_task(project_id: int):
    return repo.get_active_task(project_id)


def describe_task(task: dict | None) -> str:
    if not task:
        return "none (the project is complete)"
    return (f"Task {task['position']}: {task['title']}\nWhat to do: {task['description']}\n"
            f"Expected output: {task['expected_output']}\nAttempts so far: {task['attempts']}")


def roadmap_summary(tasks: list[dict]) -> str:
    return "; ".join(f"{t['position']}. {t['title']}" for t in tasks)


def status_label(task: dict) -> str:
    return {"passed": "Completed", "active": "In progress", "locked": "Locked"}[task["status"]]
