"""Tiny Markdown renderer for read-only tk.Text widgets (selectable, copyable)."""
from __future__ import annotations

import math
import re
import tkinter as tk
from tkinter import font as tkfont

from interface import theme
from utils.helpers import strip_non_bmp

INLINE = re.compile(r"(\*\*[^*\n]+\*\*|`[^`\n]+`)")
HEADING = re.compile(r"^\s{0,3}(#{1,4})\s+(.*)$")
BULLET = re.compile(r"^(\s*)[-*•]\s+(.*)$")
NUMBERED = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")


def make_text(parent, size: int = 12, bg: str | None = None) -> tk.Text:
    base = (theme.FAMILY, size)
    w = tk.Text(parent, wrap="word", bd=0, highlightthickness=0, relief="flat", padx=0, pady=2, height=1, width=10,
                bg=bg or theme.resolve("bg"), fg=theme.resolve("text"), font=base, cursor="arrow", insertwidth=0,
                selectbackground=theme.resolve("accent"), selectforeground="#ffffff", takefocus=0)
    bold = tkfont.Font(family=theme.FAMILY, size=size, weight="bold")
    mono = tkfont.Font(family=theme.MONO, size=size - 1)
    w._fonts = (bold, mono)  # keep references alive
    w.tag_configure("bold", font=bold)
    w.tag_configure("h", font=bold, foreground=theme.resolve("accent"))
    w.tag_configure("code_inline", font=mono, background=theme.resolve("code_bg"))
    w.tag_configure("code_block", font=mono, background=theme.resolve("code_bg"), lmargin1=10, lmargin2=10, rmargin=10)
    w.tag_configure("bullet", lmargin1=12, lmargin2=28)
    w.tag_configure("ok", foreground=theme.resolve("ok"), lmargin1=12, lmargin2=28)
    w.tag_configure("bad", foreground=theme.resolve("bad"), lmargin1=12, lmargin2=28)
    w.tag_configure("warn", foreground=theme.resolve("warn"), lmargin1=12, lmargin2=28)
    w.tag_configure("muted", foreground=theme.resolve("muted"))
    return w


def _inline(w: tk.Text, text: str, tags: tuple = ()) -> None:
    for part in INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            w.insert("end", part[2:-2], tags + ("bold",))
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            w.insert("end", part[1:-1], tags + ("code_inline",))
        else:
            w.insert("end", part, tags)


def render(w: tk.Text, text: str) -> None:
    w.configure(state="normal")
    w.delete("1.0", "end")
    in_code = False
    for line in strip_non_bmp(text).split("\n"):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            w.insert("end", (line or " ") + "\n", ("code_block",))
            continue
        h, b, n = HEADING.match(line), BULLET.match(line), NUMBERED.match(line)
        if h:
            _inline(w, h.group(2), ("h",))
        elif line.startswith(("✔",)):
            _inline(w, line, ("ok",))
        elif line.startswith(("✘",)):
            _inline(w, line, ("bad",))
        elif line.startswith(("⚠", "[Code removed")):
            _inline(w, line, ("warn",))
        elif b:
            _inline(w, "•  " + b.group(2), ("bullet",))
        elif n:
            _inline(w, f"{n.group(2)}.  {n.group(3)}", ("bullet",))
        else:
            _inline(w, line)
        w.insert("end", "\n")
    w.delete("end-2c", "end-1c")  # trailing newline
    w.configure(state="disabled")


def fit_height(w: tk.Text) -> None:
    """Resize a Text widget to exactly fit its wrapped content."""
    try:
        w.update_idletasks()
        res = w.count("1.0", "end", "ypixels")
        px = res[0] if res else 0
        line = tkfont.Font(font=w.cget("font")).metrics("linespace") or 16
        lines = max(1, math.ceil(px / line))
        if int(w.cget("height")) != lines:
            w.configure(height=lines)
    except tk.TclError:
        pass


def forward_wheel(w: tk.Widget, canvas) -> None:
    """Let the mouse wheel scroll the surrounding scrollable frame."""
    def on_wheel(event):
        if event.num == 4:
            canvas.yview_scroll(-3, "units")
        elif event.num == 5:
            canvas.yview_scroll(3, "units")
        else:
            step = int(-event.delta / 120) if abs(event.delta) >= 120 else (-1 if event.delta > 0 else 1)
            canvas.yview_scroll(step * 3, "units")
        return "break"
    for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        w.bind(seq, on_wheel)
