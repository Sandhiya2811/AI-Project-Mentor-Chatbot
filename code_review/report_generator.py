"""Renders the structured review as readable Markdown-lite (shown in chat and stored in the DB)."""
from __future__ import annotations

from code_review.file_reader import Bundle
from validation.validation_engine import FAILED, NEEDS, PASSED, ValidationResult


def _bullets(items, mark="•") -> list[str]:
    return [f"{mark} {i}".strip() for i in items] if items else ["• (nothing to report)"]


def render(task: dict, attempt: int, bundle: Bundle, analysis: dict, vr: ValidationResult, llm: dict | None,
           status: str, reasons: list[str], next_task: dict | None, project_done: bool) -> str:
    L: list[str] = ["# Code Review Report", f"**Task:** {task['position']}. {task['title']}",
                    f"**Attempt:** {attempt}", f"**Status:** {status}", "", "## Submitted files"]
    files = [f"{f.rel}  ({f.language or f.kind}{', ' + str(f.loc) + ' lines' if f.loc else ''})" for f in bundle.files]
    L += _bullets(files[:25]) + ([f"• ... and {len(files) - 25} more"] if len(files) > 25 else [])
    for name, why in bundle.skipped[:8]:
        L.append(f"• skipped: {name} ({why})")

    L += ["", "## What is implemented correctly"]
    ok = [f"✔ {r.description} - {r.evidence}" for r in vr.rules if r.status == "passed"]
    ok += [f"✔ {s}" for s in (llm or {}).get("implemented_correctly", [])]
    L += _bullets(ok, "")

    L += ["", "## What is missing"]
    miss = [f"✘ {r.description} - {r.evidence}" for r in vr.rules if r.status == "failed"]
    miss += [f"✘ {s}" for s in (llm or {}).get("missing", [])]
    L += _bullets(miss, "")

    L += ["", "## Detected errors"]
    errs = [f"{i.file}:{i.line} [{i.tool}] {i.message}" for i in vr.static.errors]
    L += _bullets(errs[:12])

    L += ["", "## Code quality observations"]
    obs = []
    if analysis["total_loc"]:
        obs.append(f"{analysis['total_loc']} lines of code, {analysis['function_count']} function(s), "
                   f"{analysis['class_count']} class(es), {analysis['comment_lines']} comment line(s)")
    if analysis["frameworks"]:
        obs.append("Detected libraries/frameworks: " + ", ".join(analysis["frameworks"]))
    warnings = [i for i in vr.static.issues if i.severity == "warning"]
    obs += [f"{i.file}:{i.line} [{i.tool}] {i.message}" for i in warnings[:8]]
    if len(warnings) > 8:
        obs.append(f"... {len(warnings) - 8} more lint warning(s)")
    for f in analysis["files"]:
        if f["long_functions"]:
            obs.append(f"{f['file']}: very long function(s): {', '.join(f['long_functions'][:3])}")
    obs += (llm or {}).get("observations", [])
    L += _bullets(obs[:20])

    L += ["", "## Improvement suggestions"]
    sugg = list((llm or {}).get("suggestions", []))
    if not sugg and status != PASSED:
        sugg = list(task.get("hints", [])) or ["Re-read the task description and the failed checks above."]
    L += _bullets(sugg[:8])

    L += ["", "## Validation result", f"**{status}**"] + [f"• {r}" for r in reasons]
    L += [f"• [{r.status}] {r.description}" for r in vr.rules]

    L += ["", "## Checks that could not be performed"]
    L += _bullets(vr.not_performed[:12]) if vr.not_performed else ["• None - every planned check ran."]
    if llm is None:
        L.append("• AI semantic review was not available for this submission.")

    L += ["", "## Next recommended action"]
    if status == PASSED:
        L.append("Project complete - see the final message below." if project_done else
                 f"Task approved. Next: Task {next_task['position']} - {next_task['title']}." if next_task else "Task approved.")
    elif status == FAILED:
        L.append("Fix the failed required checks and the detected errors, then resubmit (Submit for review).")
    else:
        L.append("Close the gaps listed above, then resubmit (Submit for review). Ask me for hints any time.")
    if llm and llm.get("mentor_message"):
        L += ["", "## Mentor feedback", llm["mentor_message"]]
    return "\n".join(L)
