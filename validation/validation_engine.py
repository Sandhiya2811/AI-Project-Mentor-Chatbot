"""Combines static analysis + rule checks, then decides the final status.

Decision policy (the LLM can only make the verdict STRICTER, never more lenient):
  Failed Validation  - a required hard check failed (missing files, syntax errors, failing tests...)
  Needs Improvement  - a required content check failed, or the semantic reviewer is not satisfied
  Passed             - every required check that could be performed passed (and at least one was performed)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from code_review.file_reader import Bundle
from validation import rule_validator, static_analyzer
from validation.rule_validator import RuleResult
from validation.static_analyzer import StaticResult

PASSED, NEEDS, FAILED = "Passed", "Needs Improvement", "Failed Validation"


@dataclass
class ValidationResult:
    rules: list[RuleResult]
    static: StaticResult
    not_performed: list[str] = field(default_factory=list)


def validate(checks: list[dict], bundle: Bundle, analysis: dict) -> ValidationResult:
    static = static_analyzer.analyze(bundle)
    rules = rule_validator.run_checks(checks, bundle, analysis, static)
    not_performed = list(static.not_performed)
    not_performed += [f"Check '{r.description}' - {r.evidence}" for r in rules if r.status == "skipped"]
    return ValidationResult(rules, static, not_performed)


def decide(vr: ValidationResult, llm_review: dict | None) -> tuple[str, list[str]]:
    reasons: list[str] = []
    required = [r for r in vr.rules if r.required]
    performed = [r for r in required if r.status != "skipped"]
    if not performed:
        return NEEDS, ["No automated check could be performed, so the work cannot be approved yet."]
    hard_fail = [r for r in performed if r.status == "failed" and r.hard]
    soft_fail = [r for r in performed if r.status == "failed" and not r.hard]
    if hard_fail:
        return FAILED, [f"Failed required check: {r.description}" for r in hard_fail]
    if soft_fail:
        return NEEDS, [f"Requirement not met: {r.description}" for r in soft_fail]
    if llm_review is None:
        reasons.append("Semantic (AI) review was unavailable; this decision is based on the automated checks only.")
        return PASSED, reasons
    verdict = str(llm_review.get("verdict", "")).lower()
    if verdict in ("needs_improvement", "fail"):
        return NEEDS, ["All automated checks passed, but the semantic review found gaps (see below)."]
    return PASSED, reasons
