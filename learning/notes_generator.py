"""Learning notes for every technology of a project.

1. `ensure_base_notes` - instant, offline: catalog facts + verified official links + a learning path tied to the tasks.
2. `generate_notes`    - AI-written beginner explanation (sections 1-7) in the student's language; the application
   appends sections 8-9 (verified links and learning order) itself, so no URL ever comes from the model. It streams, can
   be cancelled (so a chat message always has priority) and skips notes that already exist.
"""
from __future__ import annotations

import logging

from ai_engine import prompts
from ai_engine.llm_provider import LLMError, LLMUnavailable, get_provider
from ai_engine.response_guard import check as guard_check
from database import repository as repo
from learning import resource_manager
from rag import retriever

log = logging.getLogger(__name__)
PATH_NOTE = "Learning path (start here)"


def ensure_base_notes(project_id: int) -> int:
    """Create offline notes (and the learning path) for tools that have no note yet. Never calls the LLM."""
    project, tools, tasks = repo.get_project(project_id), repo.list_requirements(project_id, "tool"), repo.list_tasks(project_id)
    existing = {n["tool_name"] for n in repo.list_notes(project_id)}
    made = 0
    repo.save_note(project_id, PATH_NOTE, "English", resource_manager.learning_path(project, tools, tasks), "", -1, "offline")
    for i, tool in enumerate(tools):
        if tool["name"] in existing:
            continue
        repo.save_note(project_id, tool["name"], "English",
                       resource_manager.offline_note(tool["name"], tool["detail"], resource_manager.find_doc(tool["name"]),
                                                     project, i + 1, len(tools), tasks,
                                                     tools[i - 1]["name"] if i else "", tools[i + 1]["name"] if i + 1 < len(tools) else ""),
                       resource_manager.find_doc(tool["name"]), i, "offline")
        made += 1
    return made


def _generate_one(project, tool, i, tools, tasks, language, skill, cancel) -> str | None:
    """Returns the finished note or None if cancelled."""
    chunks = retriever.retrieve(f"{tool['name']} {project['title']}", k=2)
    uses = resource_manager.tasks_using(tool["name"], tasks)
    prompt = prompts.TOOLS_NOTE_PROMPT.format(
        language=language, project=project["title"], objective=project["objective"], tool=tool["name"],
        role=tool["detail"] or "supporting tool", tasks=", ".join(f"Task {t['position']}: {t['title']}" for t in uses) or "general use",
        skill=skill, knowledge=retriever.format_chunks(chunks, 1200) or "(none)")
    msgs = [{"role": "system", "content": prompts.NO_CODE_RULES}, {"role": "user", "content": prompt}]
    text = ""
    for piece in get_provider().stream_chat(msgs, temperature=0.4, max_tokens=1300, cancel=cancel):
        text += piece
    if cancel is not None and cancel.is_set():
        return None
    text = guard_check(text, max_lines=3).text.strip()
    if not text:
        raise LLMError("empty note")
    return (f"# {tool['name']}\n\n{text}\n\n" + resource_manager.resource_sections(
        tool["name"], i + 1, len(tools), tasks, tools[i - 1]["name"] if i else "",
        tools[i + 1]["name"] if i + 1 < len(tools) else ""))


def generate_notes(project_id: int, language: str, skill: str = "beginner", force: bool = False,
                   on_progress=None, cancel=None) -> dict:
    """Returns {'ai': n, 'offline': n, 'error': str, 'cancelled': bool}. Never raises for LLM problems."""
    project, tools = repo.get_project(project_id), repo.list_requirements(project_id, "tool")
    tasks = repo.list_tasks(project_id)
    ensure_base_notes(project_id)
    existing = {n["tool_name"]: n for n in repo.list_notes(project_id)}
    result = {"ai": 0, "offline": 0, "error": "", "cancelled": False}
    for i, tool in enumerate(tools):
        if cancel is not None and cancel.is_set():
            result["cancelled"] = True
            break
        note = existing.get(tool["name"])
        if not force and note and note["source"] == "llm" and note["language"] == language:
            continue
        if on_progress:
            on_progress(f"Preparing AI note {i + 1}/{len(tools)}: {tool['name']}")
        try:
            text = _generate_one(project, tool, i, tools, tasks, language, skill, cancel)
        except (LLMUnavailable, LLMError) as exc:
            result["error"] = str(exc)
            log.warning("AI notes stopped: %s", exc)
            break
        if text is None:
            result["cancelled"] = True
            break
        repo.save_note(project_id, tool["name"], language, text, resource_manager.find_doc(tool["name"]), i, "llm")
        result["ai"] += 1
    return result
