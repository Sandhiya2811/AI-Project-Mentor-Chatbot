"""Orchestrates a full submission review: ingest -> analyse -> static checks -> rules -> LLM -> decision -> persist."""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ai_engine import prompts
from ai_engine.llm_provider import LLMError, get_provider
from ai_engine.response_guard import check as guard_check
from code_review import code_analyzer, file_reader, report_generator
from config import LLM_CODE_BUDGET_CHARS, UPLOAD_DIR
from database import repository as repo
from project_manager import progress_tracker
from utils.helpers import dumps, extract_json, truncate
from validation import validation_engine
from validation.validation_engine import PASSED

log = logging.getLogger(__name__)


@dataclass
class ReviewOutcome:
    status: str
    report_md: str
    passed: bool
    submission_id: int
    next_task: dict | None = None
    project_done: bool = False
    llm_review: dict | None = None
    reasons: list[str] = field(default_factory=list)


def _evidence(vr) -> str:
    lines = [f"- [{r.status}] {r.description}: {r.evidence}" for r in vr.rules]
    lines += [f"- static {i.severity}: {i.file}:{i.line} {i.message}" for i in vr.static.issues[:10]]
    return "\n".join(lines) or "(none)"


def _files_for_llm(bundle) -> str:
    files = [f for f in bundle.files if f.kind in ("code", "text", "data", "doc") and (f.text or f.extra_text)]
    if not files:
        return "(no readable files)"
    share = max(1500, LLM_CODE_BUDGET_CHARS // len(files))
    return "\n\n".join(f"=== {f.rel} ({f.language or f.kind}) ===\n{truncate(f.text + chr(10) + f.extra_text, share)}"
                       for f in files)


def _guard_review(review: dict) -> dict:
    clean = {"verdict": str(review.get("verdict", "")).lower()}
    for key in ("implemented_correctly", "missing", "observations", "suggestions"):
        items = review.get(key) or []
        clean[key] = [guard_check(str(i)).text for i in (items if isinstance(items, list) else [items])][:10]
    clean["mentor_message"] = guard_check(str(review.get("mentor_message") or "")).text
    return clean


def semantic_review(project, task, bundle, vr, language_rule) -> dict | None:
    prompt = prompts.REVIEW_PROMPT.format(
        language_rule=language_rule, task_title=task["title"], task_desc=task["description"],
        task_out=task["expected_output"], project_language=project["programming_language"],
        evidence=_evidence(vr), files=_files_for_llm(bundle))
    msgs = [{"role": "system", "content": prompts.JSON_SYSTEM}, {"role": "user", "content": prompt}]
    try:
        llm = get_provider()
        for _ in range(2):
            try:
                data = extract_json(llm.chat(msgs, temperature=0.2, max_tokens=2500, json_mode=True))
                if isinstance(data, dict) and data.get("verdict"):
                    return _guard_review(data)
            except ValueError:
                continue
    except LLMError as exc:
        log.warning("Semantic review unavailable: %s", exc)
    return None


def review(project: dict, task: dict, paths: list[Path], notes: str, language_rule: str,
           on_status=None) -> ReviewOutcome:
    say = on_status or (lambda s: None)
    attempt = progress_tracker.record_attempt(task["id"])
    sid = repo.create_submission(project["id"], task["id"], attempt, notes)            # Pending Review
    dest = UPLOAD_DIR / str(project["id"]) / f"submission_{sid}"
    try:
        repo.set_submission_status(sid, "Under Review")
        say("Reading submitted files...")
        bundle = file_reader.ingest(paths, dest)
        say("Analysing structure and running static checks...")
        analysis = code_analyzer.analyze(bundle)
        vr = validation_engine.validate(task["checks"], bundle, analysis)
        say("Asking the AI mentor for a semantic review...")
        llm = semantic_review(project, task, bundle, vr, language_rule)
        status, reasons = validation_engine.decide(vr, llm)
    except Exception:
        repo.set_submission_status(sid, "Pending Review")
        shutil.rmtree(dest, ignore_errors=True)
        raise
    for f in bundle.files:
        repo.add_uploaded_file(sid, f.rel, str(f.path), f.size, f.sha256, f.language, f.kind)
    next_task, done = None, False
    if status == PASSED:
        progress, next_task = progress_tracker.mark_passed(project["id"], task)
        done = next_task is None
    report_md = report_generator.render(task, attempt, bundle, analysis, vr, llm, status, reasons, next_task, done)
    repo.set_submission_status(sid, status)
    repo.add_report(sid, task["id"], status, [r.to_dict() for r in vr.rules], vr.static.to_dict(), llm,
                    vr.not_performed, report_md)
    repo.log_activity(project.get("user_id"), project["id"], "submission", f"task {task['id']} attempt {attempt}: {status}")
    return ReviewOutcome(status, report_md, status == PASSED, sid, next_task, done, llm, reasons)
