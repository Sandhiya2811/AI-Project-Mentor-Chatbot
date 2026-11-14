from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

EXT_LANG = {
    ".py": "Python", ".ipynb": "Python", ".java": "Java", ".c": "C", ".h": "C", ".cpp": "C++", ".cc": "C++",
    ".cxx": "C++", ".hpp": "C++", ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".php": "PHP", ".r": "R", ".go": "Go", ".rb": "Ruby",
    ".cs": "C#", ".sql": "SQL", ".html": "HTML", ".htm": "HTML", ".css": "CSS", ".scss": "CSS", ".sh": "Shell",
    ".kt": "Kotlin", ".swift": "Swift", ".rs": "Rust", ".vue": "JavaScript", ".dart": "Dart", ".scala": "Scala",
    ".lua": "Lua", ".pl": "Perl", ".m": "Objective-C",
}
SHEBANG = {"python": "Python", "node": "JavaScript", "ruby": "Ruby", "php": "PHP", "bash": "Shell", "sh": "Shell",
           "Rscript": "R", "perl": "Perl"}
MANIFESTS = {"requirements.txt": "Python", "pyproject.toml": "Python", "setup.py": "Python", "pipfile": "Python",
             "pom.xml": "Java", "build.gradle": "Java", "package.json": "JavaScript", "tsconfig.json": "TypeScript",
             "go.mod": "Go", "composer.json": "PHP", "gemfile": "Ruby", "description": "R", "cargo.toml": "Rust"}
MARKUP = {"HTML", "CSS", "SQL"}


def detect_file(name: str, text: str | None = None) -> str | None:
    lang = EXT_LANG.get(Path(name).suffix.lower())
    if lang:
        return lang
    if text and text.startswith("#!"):
        first = text.splitlines()[0]
        for key, value in SHEBANG.items():
            if re.search(rf"\b{key}\b", first):
                return value
    return None


def detect_project(files) -> tuple[str, dict[str, int]]:
    """files: iterable of objects with .language, .rel, .loc (optional). Returns (primary, {lang: weight})."""
    weights: Counter = Counter()
    for f in files:
        if f.language:
            weight = max(1, getattr(f, "loc", 1))
            weights[f.language] += weight // 2 if f.language in MARKUP else weight
    if not weights:
        for f in files:
            lang = MANIFESTS.get(Path(f.rel).name.lower())
            if lang:
                weights[lang] += 1
    primary = weights.most_common(1)[0][0] if weights else "Unknown"
    return primary, dict(weights)
