"""Turns a free-text project idea into a structured analysis (LLM), with an honest offline fallback."""
from __future__ import annotations

import re

from ai_engine import prompts
from ai_engine.llm_provider import LLMError, get_provider
from utils.helpers import extract_json, short_title

LANG_KEYWORDS = [("Java", r"\bjava\b(?!script)"), ("JavaScript", r"\b(javascript|node\.?js|react|express)\b"),
                 ("TypeScript", r"\btypescript\b"), ("C++", r"c\+\+"), ("C#", r"c#|\.net"), ("PHP", r"\bphp\b"),
                 ("Go", r"\b(golang|go language)\b"), ("Ruby", r"\bruby\b"), ("R", r"\br language\b|\brstudio\b"),
                 ("C", r"\bc language\b|\bin c\b")]


def guess_language(text: str) -> str:
    low = text.lower()
    for name, pat in LANG_KEYWORDS:
        if re.search(pat, low):
            return name
    return "Python"


def _normalize(raw: dict, idea: str) -> dict:
    tools, seen = [], set()
    for t in raw.get("tools") or []:
        name = (t.get("name") if isinstance(t, dict) else str(t) or "").strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            tools.append({"name": name[:60], "role": str(t.get("role", ""))[:300] if isinstance(t, dict) else ""})
    language = str(raw.get("programming_language") or guess_language(idea)).strip()
    return {
        "title": str(raw.get("title") or short_title(idea, 60)).strip()[:90],
        "objective": str(raw.get("objective") or idea).strip()[:500],
        "domain": str(raw.get("domain") or "Software").strip()[:60],
        "programming_language": language[:30],
        "difficulty": str(raw.get("difficulty") or "beginner").lower()[:20],
        "tools": tools[:14] or [{"name": language, "role": "main programming language"}],
        "requirements": [str(r)[:200] for r in (raw.get("requirements") or [])][:8],
    }


def analyze(idea: str, skill: str = "beginner") -> dict:
    """Raises LLMUnavailable / LLMError if the model cannot be used."""
    llm = get_provider()
    msgs = [{"role": "system", "content": prompts.JSON_SYSTEM},
            {"role": "user", "content": prompts.IDEA_PROMPT.format(idea=idea, skill=skill)}]
    last = None
    for _ in range(2):
        try:
            return _normalize(extract_json(llm.chat(msgs, temperature=0.2, json_mode=True)), idea)
        except ValueError as exc:
            last = exc
    raise LLMError(f"The model did not return a usable project analysis ({last}).")


def fallback_analysis(idea: str) -> dict:
    lang = guess_language(idea)
    return _normalize({"title": short_title(idea, 60), "objective": idea, "programming_language": lang,
                       "tools": [{"name": lang, "role": "main programming language"},
                                 {"name": "Git and GitHub", "role": "version control for your project"}]}, idea)
