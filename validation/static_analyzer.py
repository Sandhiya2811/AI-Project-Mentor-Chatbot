"""Language-specific static / syntax checks.

Nothing here executes student code: Python is parsed with `ast`; other languages use each toolchain's
syntax-only mode (node --check, php -l, ruby -c, gcc -fsyntax-only, javac -proc:none, gofmt -e, parse() in R).
External tools run inside the sandbox runner on a throw-away copy. Missing tools are reported, never faked.
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from code_review.file_reader import Bundle, SubFile
from utils import sandbox

LINE_RE = re.compile(r"(?:^|[:\s(])(\d{1,6})(?::\d+)?[:)\s]")


@dataclass
class Issue:
    file: str
    line: int
    severity: str  # error | warning | info
    tool: str
    message: str


@dataclass
class StaticResult:
    issues: list[Issue] = field(default_factory=list)
    tools_run: list[str] = field(default_factory=list)
    not_performed: list[str] = field(default_factory=list)
    syntax_checked: int = 0
    syntax_errors: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]


def _ruff_cmd():
    if shutil.which("ruff"):
        return ["ruff"]
    r = sandbox.run([sys.executable, "-m", "ruff", "--version"], cwd=tempfile.gettempdir(), timeout=10)
    return [sys.executable, "-m", "ruff"] if r.returncode == 0 else None


def _py_syntax(sf: SubFile, res: StaticResult) -> bool:
    src = "\n".join("# " + l if l.lstrip().startswith(("%", "!")) else l for l in sf.text.splitlines())
    res.syntax_checked += 1
    try:
        ast.parse(src)
        return True
    except SyntaxError as exc:
        res.syntax_errors += 1
        res.issues.append(Issue(sf.rel, exc.lineno or 0, "error", "python-ast", f"SyntaxError: {exc.msg}"))
    except (ValueError, RecursionError) as exc:
        res.syntax_errors += 1
        res.issues.append(Issue(sf.rel, 0, "error", "python-ast", f"Cannot parse: {exc}"))
    return False


class _Tags(HTMLParser):
    VOID = {"br", "img", "meta", "link", "input", "hr", "area", "base", "col", "embed", "source", "track", "wbr", "!doctype"}

    def __init__(self):
        super().__init__()
        self.stack: list[str] = []
        self.problems: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.stack:
            while self.stack and self.stack[-1] != tag:
                self.problems.append(f"<{self.stack.pop()}> is not closed")
            self.stack.pop()
        else:
            self.problems.append(f"unexpected </{tag}>")


def _html(sf: SubFile, res: StaticResult) -> None:
    p = _Tags()
    p.feed(sf.text)
    problems = p.problems + [f"<{t}> is not closed" for t in p.stack]
    res.syntax_checked += 1
    for msg in problems[:5]:
        res.issues.append(Issue(sf.rel, 0, "warning", "html-structure", msg))


# language -> (tool binary, argv template). {f}=file path, {out}=scratch dir
SYNTAX_TOOLS = {
    "JavaScript": ("node", ["node", "--check", "{f}"]),
    "PHP": ("php", ["php", "-l", "{f}"]),
    "Ruby": ("ruby", ["ruby", "-c", "{f}"]),
    "Go": ("gofmt", ["gofmt", "-e", "{f}"]),
    "R": ("Rscript", ["Rscript", "-e", "invisible(parse(file='{f}'))"]),
    "C": ("gcc", ["gcc", "-fsyntax-only", "-I", ".", "{f}"]),
    "C++": ("g++", ["g++", "-fsyntax-only", "-I", ".", "{f}"]),
}


def _external(sf: SubFile, work: str, res: StaticResult, tool: str, argv: list[str]) -> None:
    cmd = [a.replace("{f}", sf.rel) for a in argv]
    r = sandbox.run(cmd, cwd=work, timeout=30, isolate_network=sandbox.network_isolation_available())
    res.syntax_checked += 1
    if r.error or r.timed_out:
        res.syntax_checked -= 1
        res.not_performed.append(f"{sf.rel}: {tool} could not complete ({'timeout' if r.timed_out else r.error})")
        return
    if r.returncode != 0:
        res.syntax_errors += 1
        msg = (r.stderr or r.stdout).strip().splitlines()
        text = next((m for m in msg if "error" in m.lower()), msg[0] if msg else "syntax error")
        m = LINE_RE.search(text)
        res.issues.append(Issue(sf.rel, int(m.group(1)) if m else 0, "error", tool, text[:240]))


def analyze(bundle: Bundle) -> StaticResult:
    res = StaticResult()
    code = bundle.code_files
    if not code:
        return res  # text-only submission: nothing to analyse (has_source_files covers code tasks)
    with tempfile.TemporaryDirectory(prefix="mentor_static_") as work:
        shutil.copytree(bundle.root, work, dirs_exist_ok=True, symlinks=False)
        by_lang: dict[str, list[SubFile]] = {}
        for sf in code:
            by_lang.setdefault(sf.language or "Unknown", []).append(sf)
        for lang, files in by_lang.items():
            if lang == "Python":
                ok = [sf for sf in files if _py_syntax(sf, res)]
                res.tools_run.append("python-ast")
                cmd = _ruff_cmd()
                if cmd and ok and not any(sf.notebook for sf in ok):
                    r = sandbox.run(cmd + ["check", "--isolated", "--no-cache", "--select", "F,E9,E7,B",
                                           "--output-format", "json", "."], cwd=work, timeout=40)
                    try:
                        for item in json.loads(r.stdout or "[]"):
                            rel = Path(item["filename"]).resolve().relative_to(Path(work).resolve()).as_posix()
                            res.issues.append(Issue(rel, item["location"]["row"], "warning", "ruff",
                                                    f"{item['code']}: {item['message']}"))
                        res.tools_run.append("ruff")
                    except (ValueError, KeyError):
                        res.not_performed.append("ruff produced unreadable output")
                else:
                    res.not_performed.append("Python: ruff not installed (pip install ruff) - lint skipped.")
            elif lang == "HTML":
                for sf in files:
                    _html(sf, res)
                res.tools_run.append("html-structure")
            elif lang == "Java":
                if shutil.which("javac"):
                    out = Path(work) / "_out"
                    out.mkdir()
                    r = sandbox.run(["javac", "-proc:none", "-Xlint:all", "-d", str(out)] + [f.rel for f in files],
                                    cwd=work, timeout=60)
                    res.syntax_checked += len(files)
                    res.tools_run.append("javac")
                    for ln in (r.stderr or "").splitlines():
                        m = re.match(r"(.+?\.java):(\d+): (error|warning): (.*)", ln)
                        if m:
                            res.issues.append(Issue(m.group(1), int(m.group(2)),
                                                    "error" if m.group(3) == "error" else "warning", "javac", m.group(4)))
                            res.syntax_errors += m.group(3) == "error"
                else:
                    res.not_performed.append("Java: 'javac' not installed - compile check skipped.")
            elif lang == "SQL":
                if shutil.which("sqlfluff"):
                    for sf in files:
                        r = sandbox.run(["sqlfluff", "lint", "--dialect", "ansi", "--format", "json", sf.rel], cwd=work, timeout=40)
                        try:
                            for item in json.loads(r.stdout or "[]"):
                                for v in item.get("violations", [])[:20]:
                                    res.issues.append(Issue(sf.rel, v.get("line_no", 0), "warning", "sqlfluff",
                                                            f"{v.get('code')}: {v.get('description')}"))
                        except ValueError:
                            pass
                    res.tools_run.append("sqlfluff")
                else:
                    res.not_performed.append("SQL: 'sqlfluff' not installed - lint skipped.")
            elif lang in SYNTAX_TOOLS:
                binary, argv = SYNTAX_TOOLS[lang]
                exe = shutil.which(binary) or (shutil.which("clang") if lang in ("C", "C++") else None)
                if exe:
                    argv = [exe if a == binary else a for a in argv]
                    for sf in files:
                        _external(sf, work, res, binary, argv)
                    res.tools_run.append(binary)
                else:
                    res.not_performed.append(f"{lang}: '{binary}' not installed - syntax check skipped.")
            else:
                res.not_performed.append(f"{lang}: no static analyser is integrated for this language.")
        for sf in bundle.of_kind("text"):
            if sf.rel.endswith(".json"):
                try:
                    json.loads(sf.text)
                except ValueError as exc:
                    res.issues.append(Issue(sf.rel, 0, "warning", "json", f"Invalid JSON: {exc}"))
    res.issues = res.issues[:200]
    return res
