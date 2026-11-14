"""Personalised learning notes: one note per tool the project needs, in the student's language."""
from __future__ import annotations

import logging

from ai_engine import prompts
from ai_engine.llm_provider import LLMError, LLMUnavailable, get_provider
from ai_engine.response_guard import check as guard_check
from database import repository as repo
from learning import resource_manager
from rag import retriever

log = logging.getLogger(__name__)


def generate_notes(project_id: int, language: str, skill: str = "beginner", force: bool = False,
                   on_progress=None) -> dict:
    """Returns {'ai': n, 'offline': n, 'error': str}. Never raises for LLM problems."""
    project = repo.get_project(project_id)
    tools = repo.list_requirements(project_id, "tool")
    existing = {n["tool_name"]: n for n in repo.list_notes(project_id)}
    result = {"ai": 0, "offline": 0, "error": ""}
    llm_ok = True
    for i, tool in enumerate(tools):
        name = tool["name"]
        note = existing.get(name)
        if not force and note and note["source"] == "llm" and note["language"] == language:
            continue
        if on_progress:
            on_progress(f"Preparing note {i + 1}/{len(tools)}: {name}")
        doc = resource_manager.find_doc(name)
        if llm_ok:
            try:
                chunks = retriever.retrieve(f"{name} {project['title']}", k=3)
                prompt = prompts.TOOLS_NOTE_PROMPT.format(
                    language=language, project=project["title"], objective=project["objective"], tool=name,
                    role=tool["detail"] or "supporting tool", order=i + 1, total=len(tools),
                    prev=tools[i - 1]["name"] if i else "none (this is the first)",
                    nxt=tools[i + 1]["name"] if i + 1 < len(tools) else "none (this is the last)",
                    doc=doc or "none available", skill=skill, knowledge=retriever.format_chunks(chunks, 2000) or "(none)")
                text = get_provider().chat([{"role": "system", "content": prompts.NO_CODE_RULES},
                                            {"role": "user", "content": prompt}], temperature=0.4, max_tokens=2500)
                text = guard_check(text, max_lines=3).text.strip()
                if not text:
                    raise LLMError("empty note")
                repo.save_note(project_id, name, language, text, doc, i, "llm")
                result["ai"] += 1
                continue
            except (LLMUnavailable, LLMError) as exc:
                llm_ok = False
                result["error"] = str(exc)
                log.warning("Notes: LLM unavailable (%s) - writing offline notes", exc)
        if not note or note["source"] != "llm":
            repo.save_note(project_id, name, language,
                           resource_manager.offline_note(name, tool["detail"], doc, project, i + 1, len(tools)),
                           doc, i, "offline")
            result["offline"] += 1
    return result
