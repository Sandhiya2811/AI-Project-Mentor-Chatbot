"""Settings screen + profile and roadmap dialogs."""
from __future__ import annotations

import customtkinter as ctk

from config import PROVIDER_DEFAULTS, settings
from interface import markdown_text as md
from interface import theme
from utils import sandbox

LANGUAGES = ["Auto-detect", "English", "Tamil", "Tanglish", "Hindi", "Telugu", "Malayalam", "Kannada", "Bengali",
             "Marathi", "Spanish", "French", "German", "Arabic", "Chinese", "Japanese"]


class SettingsView(ctk.CTkFrame):
    def __init__(self, master, on_save, on_test, on_rebuild):
        super().__init__(master, fg_color=theme.color("bg"), corner_radius=0)
        self.on_save, self.on_test, self.on_rebuild = on_save, on_test, on_rebuild
        ctk.CTkLabel(self, text="Settings", font=theme.font(24, "bold"), anchor="w").pack(fill="x", padx=32, pady=(24, 8))
        form = ctk.CTkScrollableFrame(self, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=24)
        self.vars: dict[str, ctk.StringVar] = {}

        def section(text):
            ctk.CTkLabel(form, text=text, font=theme.font(14, "bold"), anchor="w", text_color=theme.color("accent")).pack(fill="x", padx=8, pady=(16, 4))

        def option(label, key, values):
            self.vars[key] = ctk.StringVar(value=settings.get(key) or values[0])
            row = ctk.CTkFrame(form, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=3)
            ctk.CTkLabel(row, text=label, width=170, anchor="w").pack(side="left")
            ctk.CTkOptionMenu(row, values=values, variable=self.vars[key], width=260).pack(side="left")

        def entry(label, key, placeholder="", secret=False):
            self.vars[key] = ctk.StringVar(value=settings.get(key))
            row = ctk.CTkFrame(form, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=3)
            ctk.CTkLabel(row, text=label, width=170, anchor="w").pack(side="left")
            ctk.CTkEntry(row, textvariable=self.vars[key], width=420, placeholder_text=placeholder,
                         show="*" if secret else "").pack(side="left")

        section("Appearance")
        option("Theme", "THEME", ["dark", "light", "system"])
        section("AI model (LLM)")
        option("Provider", "LLM_PROVIDER", list(PROVIDER_DEFAULTS))
        entry("Model", "LLM_MODEL", "e.g. llama3.1 / gpt-4o-mini / claude-sonnet-5-5")
        entry("Base URL", "LLM_BASE_URL", "leave empty for the provider default")
        entry("API key", "LLM_API_KEY", "not needed for Ollama", secret=True)
        section("Knowledge base (RAG)")
        option("Embedding backend", "EMBEDDING_BACKEND", ["hash", "sentence-transformers", "ollama"])
        entry("Embedding model", "EMBEDDING_MODEL", "optional")
        section("Code execution sandbox")
        option("Run student tests", "CODE_EXECUTION", ["auto", "off"])
        ctk.CTkLabel(form, text=sandbox.execution_status(), font=theme.font(12), text_color=theme.color("muted"),
                     anchor="w", wraplength=760, justify="left").pack(fill="x", padx=8)
        self.status = ctk.CTkLabel(self, text="", font=theme.font(12), text_color=theme.color("accent"), anchor="w", wraplength=860)
        self.status.pack(fill="x", padx=32, pady=(6, 0))
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=28, pady=12)
        for text, cmd, primary in (("Save", self._save, True), ("Test AI connection", self.on_test, False),
                                   ("Rebuild knowledge index", self.on_rebuild, False)):
            ctk.CTkButton(bar, text=text, command=cmd, width=170,
                          fg_color=theme.color("accent") if primary else theme.color("card"),
                          hover_color=theme.color("accent_hover") if primary else theme.color("hover"),
                          text_color="#ffffff" if primary else theme.color("text")).pack(side="left", padx=4)

    def _save(self) -> None:
        self.on_save({k: v.get().strip() for k, v in self.vars.items()})

    def values(self) -> dict:
        return {k: v.get().strip() for k, v in self.vars.items()}

    def set_status(self, text: str, ok: bool = True) -> None:
        self.status.configure(text=text, text_color=theme.color("accent" if ok else "bad"))


class _Dialog(ctk.CTkToplevel):
    def __init__(self, master, title: str, size: str):
        super().__init__(master)
        self.title(title)
        self.geometry(size)
        self.transient(master)
        self.after(150, self._modal)

    def _modal(self) -> None:
        try:
            self.lift()
            self.focus_force()
            self.grab_set()
        except Exception:
            pass


class ProfileDialog(_Dialog):
    def __init__(self, master, user: dict, on_save):
        super().__init__(master, "User Profile", "420x360")
        self.on_save = on_save
        self.name = ctk.StringVar(value=user["name"])
        self.lang = ctk.StringVar(value=user["preferred_language"])
        self.level = ctk.StringVar(value=user["skill_level"])
        pad = dict(padx=24, anchor="w")
        ctk.CTkLabel(self, text="Display name").pack(pady=(20, 2), **pad)
        ctk.CTkEntry(self, textvariable=self.name, width=360).pack(**pad)
        ctk.CTkLabel(self, text="Preferred language (replies and learning notes)").pack(pady=(14, 2), **pad)
        ctk.CTkOptionMenu(self, values=LANGUAGES, variable=self.lang, width=360).pack(**pad)
        ctk.CTkLabel(self, text="Skill level").pack(pady=(14, 2), **pad)
        ctk.CTkOptionMenu(self, values=["beginner", "intermediate", "advanced"], variable=self.level, width=360).pack(**pad)
        ctk.CTkButton(self, text="Save", fg_color=theme.color("accent"), hover_color=theme.color("accent_hover"),
                      text_color="#ffffff", command=self._ok).pack(pady=24)

    def _ok(self) -> None:
        self.on_save(self.name.get().strip() or "Student", self.lang.get(), self.level.get())
        self.destroy()


class RoadmapDialog(_Dialog):
    def __init__(self, master, project: dict, tasks: list[dict]):
        super().__init__(master, f"Roadmap - {project['title']}", "720x620")
        frame = ctk.CTkScrollableFrame(self, fg_color=theme.color("bg"))
        frame.pack(fill="both", expand=True, padx=8, pady=8)
        text = md.make_text(frame, size=13)
        text.pack(fill="x", padx=14, pady=10)
        md.forward_wheel(text, frame._parent_canvas)
        lines = [f"# {project['title']}", project["objective"], ""]
        for t in tasks:
            mark = {"passed": "✔", "active": "▶", "locked": "•"}[t["status"]]
            lines.append(f"## {mark} {t['position']}. {t['title']}  [{ {'passed': 'completed', 'active': 'current', 'locked': 'locked'}[t['status']] }]")
            if t["status"] != "locked":
                lines += [t["description"], f"**Expected output:** {t['expected_output']}", f"Attempts: {t['attempts']}", ""]
        md.render(text, "\n".join(lines))
        text.bind("<Configure>", lambda e: self.after(15, lambda: md.fit_height(text)) if e.width > 60 else None)
