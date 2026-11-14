from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def loads(text, default=None):
    if text is None or text == "":
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


def extract_json(text: str):
    """Pull the first JSON object/array out of an LLM reply (handles ``` fences and chatter)."""
    if not text or not text.strip():
        raise ValueError("empty reply")
    t = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", text.strip(), flags=re.I)
    try:
        return json.loads(t)
    except ValueError:
        pass
    starts = [i for i in (t.find("{"), t.find("[")) if i != -1]
    if not starts:
        raise ValueError("no JSON found in reply")
    start = min(starts)
    open_ch, close_ch = t[start], ("}" if t[start] == "{" else "]")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(t)):
        ch = t[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return json.loads(t[start : i + 1])
    raise ValueError("unbalanced JSON in reply")


def truncate(text: str, limit: int, suffix: str = "…") -> str:
    return text if len(text) <= limit else text[: max(0, limit - len(suffix))] + suffix


def strip_non_bmp(text: str) -> str:
    """Tk 8.6 cannot reliably render characters outside the BMP (emoji); drop them for display."""
    return "".join(ch for ch in text if ord(ch) <= 0xFFFF and ch not in "\ufe0f\u200d")


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def short_title(text: str, n: int = 48) -> str:
    one = " ".join(text.split())
    return one if len(one) <= n else one[: n - 1].rstrip() + "…"
