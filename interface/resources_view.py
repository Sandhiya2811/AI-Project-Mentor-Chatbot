"""Learning Resources: per-project notes, separate from the chat."""
from __future__ import annotations

import customtkinter as ctk

from interface import markdown_text as md
from interface import theme
from utils.helpers import short_title, strip_non_bmp


class ResourcesView(ctk.CTkFrame):
    def __init__(self, master, on_select_project, on_regenerate):
        super().__init__(master, fg_color=theme.color("bg"), corner_radius=0)
        self.on_select_project, self.on_regenerate = on_select_project, on_regenerate
        self.projects: dict[str, int] = {}
        self.notes: list[dict] = []
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=28, pady=(22, 6))
        ctk.CTkLabel(head, text="Learning Resources", font=theme.font(24, "bold")).pack(side="left")
        self.regen = ctk.CTkButton(head, text="Regenerate with AI", width=150, fg_color=theme.color("accent"),
                                   hover_color=theme.color("accent_hover"), text_color="#ffffff", command=self._regen)
        self.regen.pack(side="right")
        self.picker = ctk.CTkOptionMenu(head, values=["(no projects)"], width=260, command=self._picked,
                                        fg_color=theme.color("card"), button_color=theme.color("card"),
                                        text_color=theme.color("text"))
        self.picker.pack(side="right", padx=10)
        self.info = ctk.CTkLabel(self, text="", font=theme.font(12), text_color=theme.color("muted"), anchor="w", wraplength=900)
        self.info.pack(fill="x", padx=30)
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=10)
        self.toc = ctk.CTkScrollableFrame(body, width=230, fg_color=theme.color("card"), corner_radius=12)
        self.toc.pack(side="left", fill="y", padx=(0, 12))
        self.reader_frame = ctk.CTkScrollableFrame(body, fg_color=theme.color("card"), corner_radius=12)
        self.reader_frame.pack(side="left", fill="both", expand=True)
        self.reader = md.make_text(self.reader_frame, size=13, bg=theme.resolve("card"))
        self.reader.pack(fill="x", padx=18, pady=14)
        md.forward_wheel(self.reader, self.reader_frame._parent_canvas)
        self.reader.bind("<Configure>", lambda e: self.after(15, lambda: md.fit_height(self.reader)) if e.width > 60 else None)

    def set_projects(self, projects: list[dict], selected_id: int | None) -> None:
        self.projects = {f"{short_title(strip_non_bmp(p['title']), 34)}  (#{p['id']})": p["id"] for p in projects}
        names = list(self.projects) or ["(no projects)"]
        self.picker.configure(values=names)
        label = next((n for n, i in self.projects.items() if i == selected_id), names[0])
        self.picker.set(label)

    def current_project_id(self) -> int | None:
        return self.projects.get(self.picker.get())

    def _picked(self, _label: str) -> None:
        pid = self.current_project_id()
        if pid:
            self.on_select_project(pid)

    def _regen(self) -> None:
        pid = self.current_project_id()
        if pid:
            self.on_regenerate(pid)

    def set_info(self, text: str) -> None:
        self.info.configure(text=strip_non_bmp(text))

    def set_notes(self, notes: list[dict]) -> None:
        self.notes = notes
        for w in self.toc.winfo_children():
            w.destroy()
        if not notes:
            self._show("# No notes yet\nNotes are generated automatically when a project starts. Use **Regenerate with AI** "
                       "once your language model is reachable.")
            return
        for i, n in enumerate(notes):
            tag = "" if n["source"] == "llm" else "  (offline)"
            ctk.CTkButton(self.toc, text=f"{i + 1}. {strip_non_bmp(n['tool_name'])}{tag}", anchor="w", height=32,
                          fg_color="transparent", hover_color=theme.color("hover"), text_color=theme.color("text"),
                          command=lambda k=i: self._open(k)).pack(fill="x", pady=1)
        self._open(0)

    def _open(self, index: int) -> None:
        n = self.notes[index]
        doc = f"\n\n**Official documentation:** {n['doc_url']}" if n["doc_url"] and n["doc_url"] not in n["content_md"] else ""
        self._show(f"# {n['tool_name']}  ({n['language']})\n\n{n['content_md']}{doc}")

    def _show(self, text: str) -> None:
        md.render(self.reader, text)
        self.after(30, lambda: md.fit_height(self.reader))
