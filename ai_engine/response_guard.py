"""Independent enforcement of the NO-CODE policy.

The system prompt asks the model not to write code; this guard does not trust that. Every AI-generated
text (chat replies, review feedback, task text, learning notes) passes through `check()` before it is shown
or stored. Heuristic by nature: it blocks ready-made code, allows pseudocode and tiny syntax illustrations.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from config import MAX_SNIPPET_LINES

NOTICE = ("[Code removed by the response guard: I don't hand out ready-made code. "
          "Use the explanation / pseudocode here and write this part yourself.]")
FENCE = re.compile(r"```([^\n`]*)\n(.*?)(?:```|\Z)", re.S)
SAFE_LANGS = {"pseudocode", "pseudo", "text", "plaintext", "txt", "output", "console", "log", "algorithm",
              "markdown", "md", ""}
DEFINITION = re.compile(
    r"^\s*(?:def\s+\w+\s*\(|class\s+\w+|function\s+\w+\s*\(|async\s+def\s+\w+|func\s+\w+\s*\(|fn\s+\w+\s*\(|"
    r"(?:public|private|protected|static)\s+[\w<>\[\], ]+\s+\w+\s*\(.*\)\s*\{?|int\s+main\s*\(|void\s+\w+\s*\()",
    re.M)
STRONG = re.compile(
    r"^\s*(?:def\s+\w+\(.*\)\s*:|class\s+\w+.*:|import\s+\w+|from\s+[\w.]+\s+import|#include\s*<|"
    r"public\s+(?:static\s+)?\w+\s+\w+\(|System\.out|console\.log|print\(|\w+\s*=\s*\w+\.\w+\(.*\)\s*$)", re.M)
CODEY = re.compile(
    r"^\s*(?:def\s|class\s|import\s|from\s+\S+\s+import|return\b|print\(|public\s|private\s|#include|"
    r"for\s*\(.*\)|(?:for|while)\s+.+:\s*$|\w[\w\.\[\]]*\s*=\s*[\w\.\[\]\"']+\(.*\)\s*$|.*[;{}]\s*$)")


@dataclass
class GuardResult:
    ok: bool
    text: str
    violations: list[str] = field(default_factory=list)


def _nonempty(block: str) -> list[str]:
    return [ln for ln in block.splitlines() if ln.strip()]


def check(text: str, max_lines: int = MAX_SNIPPET_LINES) -> GuardResult:
    """Return the (possibly sanitised) text and what was violated."""
    violations: list[str] = []

    def fix(match: re.Match) -> str:
        lang = match.group(1).strip().lower()
        lines = _nonempty(match.group(2))
        if lang in SAFE_LANGS:
            strong = sum(1 for ln in lines if STRONG.match(ln))
            if len(lines) > 30 or strong >= 4:
                violations.append("pseudocode block looks like real code" if strong >= 4 else "block too long")
                return NOTICE
            return match.group(0)
        if DEFINITION.search(match.group(2)):
            violations.append("function/class definition in a code block")
            return NOTICE
        if len(lines) > max_lines:
            violations.append(f"code block of {len(lines)} lines (limit {max_lines})")
            return NOTICE
        return match.group(0)

    cleaned = FENCE.sub(fix, text)

    # code pasted without fences: a run of >= 5 code-looking lines
    out, run = [], []

    def flush():
        nonlocal run
        if len(run) >= 5:
            violations.append("unfenced code")
            out.append(NOTICE)
        else:
            out.extend(run)
        run = []

    for ln in cleaned.splitlines():
        if ln.strip() == NOTICE:
            flush()
            out.append(ln)
        elif ln.strip() and CODEY.match(ln):
            run.append(ln)
        elif not ln.strip() and run:
            run.append(ln)
        else:
            flush()
            out.append(ln)
    flush()
    cleaned = "\n".join(out)
    return GuardResult(not violations, cleaned, violations)


class StreamGuard:
    """Filters text *while it streams*, so the student sees the answer progressively but never sees forbidden code.

    Plain text is passed through immediately. A fenced block (```) is held back until its closing fence arrives and
    is then judged by `check()` - it is shown as-is or replaced by NOTICE. `finish()` flushes what is left. The final
    stored answer is still produced by a full `check()` on the complete text (it also catches unfenced code).
    """

    def __init__(self, max_lines: int = MAX_SNIPPET_LINES) -> None:
        self.max_lines = max_lines
        self.pending = ""
        self.fence = ""
        self.in_fence = False

    def _judge(self, block: str) -> str:
        return check(block, self.max_lines).text

    def feed(self, chunk: str) -> str:
        self.pending += chunk
        out: list[str] = []
        while True:
            if not self.in_fence:
                i = self.pending.find("```")
                if i == -1:
                    hold = len(self.pending) - len(self.pending.rstrip("`"))  # maybe the start of a fence
                    hold = min(hold, 2)
                    out.append(self.pending[: len(self.pending) - hold])
                    self.pending = self.pending[len(self.pending) - hold:]
                    break
                out.append(self.pending[:i])
                self.fence, self.pending, self.in_fence = self.pending[i:], "", True
            self.fence += self.pending
            self.pending = ""
            nl = self.fence.find("\n")
            j = self.fence.find("```", nl + 1) if nl != -1 else -1
            if j == -1:
                break
            block, rest = self.fence[: j + 3], self.fence[j + 3:]
            out.append(self._judge(block))
            self.fence, self.in_fence, self.pending = "", False, rest
        return "".join(out)

    def finish(self) -> str:
        out = self._judge(self.fence) if self.in_fence else ""
        out += self.pending
        self.pending, self.fence, self.in_fence = "", "", False
        return out
