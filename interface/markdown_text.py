"""Tiny Markdown renderer for read-only tk.Text widgets (selectable, copyable)."""
from __future__ import annotations

import math
import re
import tkinter as tk
import webbrowser
from tkinter import font as tkfont
from tkinter import messagebox
from urllib.parse import urlparse

from interface import theme
from utils.helpers import strip_non_bmp

INLINE = re.compile(r"(\[[^\]\n]+\]\(https?://[^\s)]+\)|\*\*[^*\n]+\*\*|`[^`\n]+`|https?://[^\s<>\]\)\"']+)")
MD_LINK = re.compile(r"^\[(.+)\]\((https?://[^\s)]+)\)$")

# Replaced in tests; they let the browser / dialog be observed without opening real windows.
_opener = webbrowser.open_new_tab
_warn = messagebox.showwarning


def is_valid_url(url: str) -> bool:
    try:
        u = urlparse(url.strip())
    except ValueError:
        return False
    return u.scheme in ("http", "https") and bool(u.netloc) and ("." in u.netloc or u.netloc.startswith("localhost"))


def open_url(url: str, widget=None) -> bool:
    """Open a link in the default browser (new tab). Invalid links and a missing browser are reported, never raised."""
    url = url.strip()
    if not is_valid_url(url):
        _warn("Link cannot be opened", f"This is not a valid web address:\n{url}")
        return False
    try:
        if _opener(url):
            return True
    except Exception:   # webbrowser can raise on unusual platforms
        pass
    if widget is not None:
        try:
            widget.clipboard_clear()
            widget.clipboard_append(url)
        except tk.TclError:
            pass
    _warn("Could not open the browser", f"Your browser could not be started. The link was copied to the clipboard:\n{url}")
    return False
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
    w._link_n = 0
    return w


def _link(w: tk.Text, label: str, url: str, tags: tuple) -> None:
    """Insert clickable text: underlined link colour, hand cursor, opens in the browser."""
    w._link_n = getattr(w, "_link_n", 0) + 1
    tag = f"link_{w._link_n}"
    w.tag_configure(tag, foreground=theme.resolve("link"), underline=True)
    w.tag_bind(tag, "<Button-1>", lambda _e, u=url, ww=w: open_url(u, ww))
    w.tag_bind(tag, "<Enter>", lambda _e, ww=w: ww.configure(cursor="hand2"))
    w.tag_bind(tag, "<Leave>", lambda _e, ww=w: ww.configure(cursor="arrow"))
    w.insert("end", label, tags + (tag,))


def _inline(w: tk.Text, text: str, tags: tuple = ()) -> None:
    for part in INLINE.split(text):
        if not part:
            continue
        m = MD_LINK.match(part)
        if m:
            _link(w, m.group(1), m.group(2), tags)
        elif part.startswith("http"):
            core = part.rstrip(".,;:!?")
            _link(w, core, core, tags)
            if len(part) > len(core):
                w.insert("end", part[len(core):], tags)
        elif part.startswith("**") and part.endswith("**") and len(part) > 4:
            w.insert("end", part[2:-2], tags + ("bold",))
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            w.insert("end", part[1:-1], tags + ("code_inline",))
        else:
            w.insert("end", part, tags)


def render(w: tk.Text, text: str) -> None:
    w.configure(state="normal")
    w.delete("1.0", "end")
    for name in w.tag_names():                      # links from the previous render (streaming re-renders often)
        if name.startswith("link_"):
            w.tag_delete(name)
    w._link_n = 0
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
