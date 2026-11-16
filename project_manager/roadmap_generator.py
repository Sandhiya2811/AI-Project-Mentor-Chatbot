"""Builds the task list. LLM proposes stages + machine-checkable rules; this module validates and hardens them."""
from __future__ import annotations

from ai_engine import prompts
from ai_engine.llm_provider import LLMError, get_provider
from ai_engine.response_guard import check as guard_check
from utils.helpers import extract_json
from validation.rule_validator import KNOWN_TYPES

DELIVERABLES = {"code", "text", "mixed"}


def _clean_check(c) -> dict | None:
    if not isinstance(c, dict) or c.get("type") not in KNOWN_TYPES:
        return None
    params = c.get("params") if isinstance(c.get("params"), dict) else {}
    return {"type": c["type"], "description": str(c.get("description") or c["type"])[:160], "params": params,
            "required": bool(c.get("required", True))}


def _guard(text: str) -> str:
    return guard_check(str(text or "")).text


def normalize_stage(stage: dict) -> dict | None:
    if not isinstance(stage, dict) or not str(stage.get("title", "")).strip():
        return None
    kind = stage.get("deliverable_type") if stage.get("deliverable_type") in DELIVERABLES else "code"
    checks = [c for c in (_clean_check(c) for c in stage.get("checks") or []) if c][:6]
    have = {c["type"] for c in checks}
    if kind in ("code", "mixed"):
        if "has_source_files" not in have:
            checks.insert(0, {"type": "has_source_files", "description": "Source file(s) submitted", "params": {"min": 1}, "required": True})
        if "syntax_valid" not in have:
            checks.append({"type": "syntax_valid", "description": "No syntax errors", "params": {}, "required": True})
    elif "text_min_words" not in have:
        checks.insert(0, {"type": "text_min_words", "description": "A real written answer (not just a few words)", "params": {"min": 30}, "required": True})
    as_list = lambda v: [x for x in (v if isinstance(v, list) else []) if str(x).strip()]  # noqa: E731
    return {"title": str(stage["title"]).strip()[:100], "description": _guard(stage.get("description")),
            "expected_output": _guard(stage.get("expected_output") or "Submit your work for this task."),
            "deliverable_type": kind, "hints": [_guard(h) for h in as_list(stage.get("hints"))][:4],
            "subtasks": [_guard(x)[:160] for x in as_list(stage.get("subtasks"))][:6],
            "tools": [str(x).strip()[:40] for x in as_list(stage.get("tools"))][:6], "checks": checks}


def final_task(language: str) -> dict:
    checks = [
        {"type": "has_source_files", "description": "Project source files are included", "params": {"min": 1}, "required": True},
        {"type": "syntax_valid", "description": "No syntax errors in the project", "params": {}, "required": True},
        {"type": "file_exists", "description": "A README file is included", "params": {"pattern": "readme*"}, "required": True},
        {"type": "text_min_words", "description": "README / notes explain the project (min. 80 words)", "params": {"min": 80}, "required": True},
        {"type": "tests_present", "description": "Automated tests are included", "params": {}, "required": True},
    ]
    if language == "Python":
        checks.append({"type": "tests_pass", "description": "Tests pass in the sandbox", "params": {}, "required": True})
    return {"title": "Final Validation and Project Completion",
            "description": ("Package your complete project as a single ZIP file: source code, tests, dependency file "
                            "and a README that explains the purpose, setup, usage and limitations. We validate the "
                            "whole project one last time."),
            "expected_output": "One ZIP containing the full project folder (source, tests, README, dependency list).",
            "deliverable_type": "code",
            "hints": ["Run the project from a clean folder following your own README.",
                      "Make sure every file you reference is inside the ZIP."],
            "subtasks": ["Re-run everything from a clean folder", "Write or update the README",
                         "Make sure tests exist and pass", "Zip the project folder and submit it"],
            "tools": [language], "checks": checks}


def generate(analysis: dict, skill: str = "beginner") -> list[dict]:
    llm = get_provider()
    tools = ", ".join(t["name"] for t in analysis["tools"])
    msgs = [{"role": "system", "content": prompts.JSON_SYSTEM},
            {"role": "user", "content": prompts.ROADMAP_PROMPT.format(
                title=analysis["title"], objective=analysis["objective"], language=analysis["programming_language"],
                tools=tools, skill=skill, check_types=prompts.CHECK_TYPES_DOC)}]
    last = None
    for _ in range(2):
        try:
            data = extract_json(llm.chat(msgs, temperature=0.3, max_tokens=3500, json_mode=True))
            stages = data.get("stages") if isinstance(data, dict) else data
            tasks = [t for t in (normalize_stage(s) for s in stages or []) if t][:9]
            if len(tasks) >= 3:
                return tasks + [final_task(analysis["programming_language"])]
            last = "too few valid stages"
        except ValueError as exc:
            last = exc
    raise LLMError(f"The model did not return a usable roadmap ({last}).")


def template_roadmap(analysis: dict) -> list[dict]:
    lang = analysis["programming_language"]
    stages = [
        ("Project Understanding", "Write down in your own words what the project must do, who will use it, its inputs and outputs, and the main steps.",
         "A short written plan (at least a paragraph).", "text", ["Start from the objective.", "List inputs, processing and outputs."]),
        ("Environment and Project Structure", f"Set up your {lang} environment and create the folder structure with an entry file and a dependency list.",
         "The starter project files.", "code", ["Keep one folder per responsibility.", "Record dependencies in a file."]),
        ("Input and Data Handling", "Implement the part that reads or receives the project's input and checks that it is valid.",
         "Source file(s) that load and validate input.", "code", ["Handle missing or malformed input.", "Test with a tiny sample first."]),
        ("Core Logic", "Implement the main processing logic of the project, split into small functions.",
         "Source file(s) containing the core logic.", "code", ["One function, one job.", "Try each function on simple examples."]),
        ("Testing and Error Handling", "Write tests for normal and edge cases and handle errors gracefully.",
         "Test file(s) plus the code they test.", "code", ["Test empty and invalid input.", "Name tests after behaviours."]),
        ("Documentation", "Write a README that explains purpose, setup, usage and limitations.",
         "A README file.", "text", ["Write for someone who has never seen the project."]),
    ]
    tasks = [normalize_stage({"title": t, "description": d, "expected_output": o, "deliverable_type": k, "hints": h,
                              "subtasks": h, "tools": [lang], "checks": []})
             for t, d, o, k, h in stages]
    tasks[4]["checks"].append({"type": "tests_present", "description": "Test files are included", "params": {}, "required": True})
    tasks[5]["checks"].append({"type": "text_min_words", "description": "README has real content (min. 60 words)", "params": {"min": 60}, "required": True})
    return tasks + [final_task(lang)]
