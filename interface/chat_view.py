from __future__ import annotations

from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from interface import markdown_text as md
from interface import theme
from utils.helpers import strip_non_bmp

MODE_ASK, MODE_SUBMIT = "Ask / chat", "Submit for review"
FILETYPES = [("Project files", "*.py *.ipynb *.java *.c *.h *.cpp *.hpp *.js *.ts *.jsx *.tsx *.php *.r *.go *.rb *.cs "
                               "*.sql *.html *.css *.md *.txt *.json *.csv *.pdf *.docx *.png *.jpg *.jpeg *.zip"),
             ("All files", "*.*")]


class Bubble(ctk.CTkFrame):
    def __init__(self, master, canvas, role: str, kind: str, text: str, attachments: list[str] | None = None):
        key = ("user_bubble" if role == "user" else "notice_bubble" if kind == "notice" else
               "review_bubble" if kind == "review" else "ai_bubble")
        super().__init__(master, corner_radius=14, fg_color=theme.color(key))
        self.text_value = text
        title = {"user": "You", "system": "Notice"}.get(role, "Review Report" if kind == "review" else "AI Project Mentor")
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(8, 0))
        ctk.CTkLabel(head, text=title, font=theme.font(11, "bold"), text_color=theme.color("muted")).pack(side="left")
        if role != "user":
            ctk.CTkButton(head, text="Copy", width=46, height=20, font=theme.font(11), fg_color="transparent",
                          hover_color=theme.color("hover"), text_color=theme.color("muted"),
                          command=self._copy).pack(side="right")
        body = text
        if attachments:
            body += "\n\n`Attached:` " + ", ".join(attachments)
        self.text = md.make_text(self, bg=theme.resolve(key))
        self.text.pack(fill="x", padx=14, pady=(2, 10))
        md.render(self.text, body)
        md.forward_wheel(self.text, canvas)
        self._pending = False
        self.text.bind("<Configure>", self._on_configure)

    def _on_configure(self, event) -> None:
        if event.width > 60 and not self._pending:
            self._pending = True
            self.after(15, self._fit)

    def _fit(self) -> None:
        self._pending = False
        md.fit_height(self.text)

    def _copy(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.text_value)


class ChatView(ctk.CTkFrame):
    def __init__(self, master, on_send, on_new_chat, on_roadmap):
        super().__init__(master, fg_color=theme.color("bg"), corner_radius=0)
        self.on_send, self.on_new_chat, self.on_roadmap = on_send, on_new_chat, on_roadmap
        self.paths: list[str] = []
        self.busy = False

        top = ctk.CTkFrame(self, fg_color=theme.color("bg"), corner_radius=0)
        top.pack(fill="x", padx=24, pady=(14, 4))
        self.title = ctk.CTkLabel(top, text="", font=theme.font(17, "bold"), anchor="w")
        self.title.pack(side="left")
        ctk.CTkButton(top, text="Roadmap", width=90, height=30, fg_color=theme.color("card"),
                      hover_color=theme.color("hover"), text_color=theme.color("text"),
                      command=self.on_roadmap).pack(side="right")
        self.progress_label = ctk.CTkLabel(top, text="", font=theme.font(12), text_color=theme.color("muted"))
        self.progress_label.pack(side="right", padx=12)
        self.progress = ctk.CTkProgressBar(top, width=150, height=8, progress_color=theme.color("accent"))
        self.progress.pack(side="right")
        self.task_label = ctk.CTkLabel(self, text="", font=theme.font(12), text_color=theme.color("muted"), anchor="w")
        self.task_label.pack(fill="x", padx=26)

        self.scroll = ctk.CTkScrollableFrame(self, fg_color=theme.color("bg"), corner_radius=0)
        self.scroll.pack(fill="both", expand=True, padx=(18, 8), pady=(6, 0))
        self.canvas = self.scroll._parent_canvas

        self.status = ctk.CTkLabel(self, text="", font=theme.font(12), text_color=theme.color("accent"), anchor="w")
        self.status.pack(fill="x", padx=28)

        box = ctk.CTkFrame(self, fg_color=theme.color("card"), corner_radius=16)
        box.pack(fill="x", padx=24, pady=(4, 16))
        self.chips = ctk.CTkFrame(box, fg_color="transparent", height=1)
        self.chips.pack(fill="x", padx=10, pady=(6, 0))
        self.mode = ctk.CTkSegmentedButton(box, values=[MODE_ASK, MODE_SUBMIT], height=26, font=theme.font(12),
                                           selected_color=theme.color("accent"),
                                           selected_hover_color=theme.color("accent_hover"))
        self.mode.set(MODE_ASK)
        self.mode.pack(anchor="w", padx=12, pady=(6, 0))
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=8)
        self.input = ctk.CTkTextbox(row, height=84, wrap="word", font=theme.font(13), corner_radius=10,
                                    fg_color=theme.color("bg"), border_width=1, border_color=theme.color("border"))
        self.input.pack(side="left", fill="x", expand=True)
        self.input.bind("<Return>", self._enter)
        buttons = ctk.CTkFrame(row, fg_color="transparent")
        buttons.pack(side="right", padx=(8, 0))
        small = dict(width=96, height=26, corner_radius=8, fg_color=theme.color("bg"),
                     hover_color=theme.color("hover"), text_color=theme.color("text"), font=theme.font(12))
        self.send_btn = ctk.CTkButton(buttons, text="Send", width=96, height=30, corner_radius=8,
                                      fg_color=theme.color("accent"), hover_color=theme.color("accent_hover"),
                                      text_color="#ffffff", command=self.submit)
        self.send_btn.grid(row=0, column=0, columnspan=2, pady=(0, 4))
        ctk.CTkButton(buttons, text="Upload file", command=self.pick_files, **small).grid(row=1, column=0, columnspan=2, pady=2)
        ctk.CTkButton(buttons, text="Clear input", command=self.clear_input, **small).grid(row=2, column=0, columnspan=2, pady=2)
        ctk.CTkButton(buttons, text="New chat", command=self.on_new_chat, **small).grid(row=3, column=0, columnspan=2, pady=2)
        ctk.CTkLabel(box, text="Enter = send, Shift+Enter = new line. In 'Submit for review' mode the text (or attached "
                               "files / ZIP) is validated against the current task.",
                     font=theme.font(11), text_color=theme.color("muted"), anchor="w", wraplength=760,
                     justify="left").pack(fill="x", padx=14, pady=(0, 8))

    # ---- transcript ---------------------------------------------------------------------------
    def clear_transcript(self) -> None:
        for child in self.scroll.winfo_children():
            child.destroy()

    def add_message(self, msg: dict, scroll: bool = True) -> None:
        role, kind = msg["role"], msg.get("kind", "chat")
        meta = msg.get("metadata") or {}
        bubble = Bubble(self.scroll, self.canvas, role, kind, msg["content"], meta.get("attachments"))
        bubble.pack(fill="x", padx=(120, 6) if role == "user" else (6, 80), pady=5, anchor="e" if role == "user" else "w")
        if scroll:
            self.after(80, lambda: self.canvas.yview_moveto(1.0))
            self.after(300, lambda: self.canvas.yview_moveto(1.0))

    def load(self, project: dict, messages: list[dict], progress: dict | None, task: dict | None) -> None:
        self.clear_transcript()
        for m in messages:
            self.add_message(m, scroll=False)
        self.after(250, lambda: self.canvas.yview_moveto(1.0))
        self.update_header(project, progress, task)
        self.clear_attachments()
        self.set_busy(False)

    def update_header(self, project: dict, progress: dict | None, task: dict | None) -> None:
        self.title.configure(text=strip_non_bmp(project["title"]))
        pct = (progress or {}).get("percent", 0) / 100
        self.progress.set(pct)
        done, total = (progress or {}).get("completed_tasks", 0), (progress or {}).get("total_tasks", 0)
        self.progress_label.configure(text=f"{done}/{total} tasks")
        self.task_label.configure(text=(f"Current task {task['position']}: {strip_non_bmp(task['title'])}" if task else
                                        "Project complete" if project["status"] == "completed" else ""))

    # ---- input ------------------------------------------------------------------------------------
    def _enter(self, event):
        if event.state & 0x1:  # Shift held -> newline
            return None
        self.submit()
        return "break"

    def submit(self) -> None:
        if self.busy:
            return
        text = self.input.get("1.0", "end-1c").strip()
        if not text and not self.paths:
            return
        mode = "submit" if (self.mode.get() == MODE_SUBMIT or self.paths) else "ask"
        paths = list(self.paths)
        self.input.delete("1.0", "end")
        self.clear_attachments()
        self.on_send(text, mode, paths)

    def pick_files(self) -> None:
        chosen = filedialog.askopenfilenames(title="Select your project files", filetypes=FILETYPES)
        if chosen:
            self.paths += [p for p in chosen if p not in self.paths]
            self.mode.set(MODE_SUBMIT)
            self._draw_chips()

    def clear_attachments(self) -> None:
        self.paths = []
        self._draw_chips()

    def _draw_chips(self) -> None:
        for w in self.chips.winfo_children():
            w.destroy()
        for p in self.paths:
            chip = ctk.CTkButton(self.chips, text=f"{Path(p).name}  x", height=24, corner_radius=12, font=theme.font(11),
                                 fg_color=theme.color("bg"), hover_color=theme.color("hover"),
                                 text_color=theme.color("text"), command=lambda q=p: self._remove(q))
            chip.pack(side="left", padx=(0, 6))

    def _remove(self, path: str) -> None:
        self.paths = [p for p in self.paths if p != path]
        self._draw_chips()

    def clear_input(self) -> None:
        self.input.delete("1.0", "end")
        self.clear_attachments()

    def set_busy(self, busy: bool, text: str = "") -> None:
        self.busy = busy
        self.send_btn.configure(state="disabled" if busy else "normal", text="Working..." if busy else "Send")
        self.status.configure(text=strip_non_bmp(text) if busy else "")

    def set_status(self, text: str) -> None:
        if self.busy:
            self.status.configure(text=strip_non_bmp(text))
