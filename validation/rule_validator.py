"""Deterministic, evidence-producing requirement checks (no LLM involved)."""
from __future__ import annotations

import fnmatch
from dataclasses import asdict, dataclass
from pathlib import Path

from code_review.file_reader import Bundle
from validation import executor
from validation.static_analyzer import StaticResult

HARD_TYPES = {"has_source_files", "file_exists", "syntax_valid", "tests_pass", "runs_ok"}
KNOWN_TYPES = HARD_TYPES | {"uses_any", "uses_all", "defines_function", "defines_class", "text_mentions",
                            "text_min_words", "tests_present", "min_lines"}


@dataclass
class RuleResult:
    id: str
    type: str
    description: str
    status: str            # passed | failed | skipped
    evidence: str
    required: bool = True
    hard: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _terms(params: dict, key: str = "terms") -> list[str]:
    raw = params.get(key) or []
    return [str(t).lower() for t in raw if str(t).strip()] if isinstance(raw, list) else []


def _check(chk: dict, bundle: Bundle, analysis: dict, static: StaticResult) -> tuple[str, str]:
    t, p = chk["type"], chk.get("params") or {}
    code = bundle.code_files
    if t == "has_source_files":
        need = int(p.get("min", 1))
        return ("passed" if len(code) >= need else "failed",
                f"{len(code)} source file(s) found" + (f": {', '.join(f.rel for f in code[:5])}" if code else ""))
    if t == "file_exists":
        pat = str(p.get("pattern", "*")).lower()
        hits = [f.rel for f in bundle.files if fnmatch.fnmatch(Path(f.rel).name.lower(), pat) or fnmatch.fnmatch(f.rel.lower(), pat)]
        return ("passed" if hits else "failed", f"matches for '{pat}': {', '.join(hits[:5]) if hits else 'none'}")
    if t == "syntax_valid":
        if static.syntax_checked == 0:
            return "skipped", "no syntax checker was available for the submitted language(s)"
        if static.syntax_errors:
            first = next((i for i in static.errors), None)
            where = f"{first.file}:{first.line} {first.message}" if first else "see static analysis"
            return "failed", f"{static.syntax_errors} syntax error(s); first: {where}"
        return "passed", f"{static.syntax_checked} file(s) checked, no syntax errors"
    if t in ("uses_any", "uses_all"):
        terms = _terms(p)
        if not code:
            return "failed", "no source files to inspect"
        if not terms:
            return "skipped", "check has no terms"
        text = bundle.code_text()
        found = [x for x in terms if x in text]
        ok = bool(found) if t == "uses_any" else len(found) == len(terms)
        return ("passed" if ok else "failed"), (f"found: {', '.join(found) or 'none'}" if ok else
                                                f"missing: {', '.join(x for x in terms if x not in text)[:160]}")
    if t == "defines_function":
        need, names = int(p.get("min_count", 1)), _terms(p, "name_contains")
        funcs = [fn for f in analysis["files"] for fn in f["functions"]]
        if names:
            funcs = [fn for fn in funcs if any(n in fn.lower() for n in names)] or []
        return ("passed" if len(funcs) >= need else "failed"), f"{len(funcs)} matching function(s): {', '.join(funcs[:6])}"
    if t == "defines_class":
        classes = [c for f in analysis["files"] for c in f["classes"]]
        need = int(p.get("min_count", 1))
        return ("passed" if len(classes) >= need else "failed"), f"{len(classes)} class(es): {', '.join(classes[:6])}"
    if t == "text_mentions":
        groups = p.get("groups") or [[x] for x in _terms(p)]
        text = bundle.corpus()
        if not text.strip():
            return "failed", "no readable text was submitted"
        missing = [g[0] for g in groups if isinstance(g, list) and g and not any(str(x).lower() in text for x in g)]
        return ("passed" if not missing else "failed"), ("all expected topics are mentioned" if not missing else
                                                          f"not found in your answer: {', '.join(map(str, missing))}")
    if t == "text_min_words":
        need = int(p.get("min", 40))
        words = len(bundle.corpus().split())
        return ("passed" if words >= need else "failed"), f"{words} words (minimum {need})"
    if t == "min_lines":
        need, loc = int(p.get("min", 10)), sum(f.loc for f in code)
        return ("passed" if loc >= need else "failed"), f"{loc} non-empty source lines (minimum {need})"
    if t == "tests_present":
        tests = analysis.get("tests", [])
        return ("passed" if tests else "failed"), (f"test files: {', '.join(tests[:5])}" if tests else "no test files found")
    if t == "tests_pass":
        return executor.run_python_tests(bundle)
    if t == "runs_ok":
        return executor.run_python_entry(bundle, p.get("entry"))
    return "skipped", f"unknown check type '{t}'"


def run_checks(checks: list[dict], bundle: Bundle, analysis: dict, static: StaticResult) -> list[RuleResult]:
    results = []
    for i, chk in enumerate(checks, 1):
        t = chk.get("type", "")
        try:
            status, evidence = _check(chk, bundle, analysis, static)
        except Exception as exc:  # a malformed check must not break the review
            status, evidence = "skipped", f"check could not be evaluated ({exc.__class__.__name__})"
        results.append(RuleResult(f"c{i}", t, chk.get("description") or t, status, evidence,
                                  bool(chk.get("required", True)), t in HARD_TYPES))
    return results
