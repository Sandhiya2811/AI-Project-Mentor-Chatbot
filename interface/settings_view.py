"""Settings screen + profile and roadmap dialogs."""
from __future__ import annotations

import customtkinter as ctk

from config import PROVIDER_INFO, settings
from interface import markdown_text as md
from interface import theme
from utils import sandbox, secrets

PROVIDER_LABELS = {k: v["label"] for k, v in PROVIDER_INFO.items()}
LABEL_TO_ID = {v: k for k, v in PROVIDER_LABELS.items()}
STATE_COLOR = {"ok": "ok", "bad": "bad", "busy": "accent", "idle": "muted"}

LANGUAGES = ["Auto-detect", "English", "Tamil", "Tanglish", "Hindi", "Telugu", "Malayalam", "Kannada", "Bengali",
             "Marathi", "Spanish", "French", "German", "Arabic", "Chinese", "Japanese"]


class SettingsView(ctk.CTkFrame):
    def __init__(self, master, on_save, on_test, on_rebuild, on_refresh_models=None, on_remove_key=None):
        super().__init__(master, fg_color=theme.color("bg"), corner_radius=0)
        self.on_save, self.on_test, self.on_rebuild = on_save, on_test, on_rebuild
        self.on_refresh_models, self.on_remove_key = on_refresh_models, on_remove_key
        self._live_models: dict[str, list[str]] = {}
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
        section("AI model (LLM) - cloud providers are the default; Ollama is optional")
        self._build_ai_section(form)
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

    # ---- AI provider section -------------------------------------------------------------------------
    def _build_ai_section(self, form) -> None:
        def row(label):
            r = ctk.CTkFrame(form, fg_color="transparent")
            r.pack(fill="x", padx=8, pady=3)
            ctk.CTkLabel(r, text=label, width=170, anchor="w").pack(side="left")
            return r

        active = settings.active_provider if settings.active_provider in PROVIDER_INFO else "openai"
        self.provider_var = ctk.StringVar(value=PROVIDER_LABELS[active])
        ctk.CTkOptionMenu(row("Provider"), values=list(PROVIDER_LABELS.values()), variable=self.provider_var, width=300,
                          command=lambda _l: self._load_provider(self.provider())).pack(side="left")
        self.hint = ctk.CTkLabel(form, text="", font=theme.font(12), text_color=theme.color("muted"), anchor="w",
                                 wraplength=760, justify="left")
        self.hint.pack(fill="x", padx=8)
        self.model_var = ctk.StringVar()
        r = row("Model")
        self.model_box = ctk.CTkComboBox(r, values=[""], variable=self.model_var, width=300)
        self.model_box.pack(side="left")
        ctk.CTkButton(r, text="Refresh models", width=130, fg_color=theme.color("card"), hover_color=theme.color("hover"),
                      text_color=theme.color("text"), command=self._refresh_models).pack(side="left", padx=8)
        self.url_var = ctk.StringVar()
        self.url_entry = ctk.CTkEntry(row("Base URL (advanced)"), textvariable=self.url_var, width=420)
        self.url_entry.pack(side="left")
        r = row("API key")
        self.key_var = ctk.StringVar()
        self.key_entry = ctk.CTkEntry(r, textvariable=self.key_var, width=420, show="*")
        self.key_entry.pack(side="left")
        ctk.CTkButton(r, text="Remove key", width=100, fg_color=theme.color("card"), hover_color=theme.color("hover"),
                      text_color=theme.color("text"), command=self._remove_key).pack(side="left", padx=8)
        self.key_info = ctk.CTkLabel(form, text="", font=theme.font(12), text_color=theme.color("muted"), anchor="w",
                                     wraplength=760, justify="left")
        self.key_info.pack(fill="x", padx=8)
        self.key_link = ctk.CTkLabel(form, text="", font=theme.font(12, "bold"), text_color=theme.color("link"), anchor="w",
                                     cursor="hand2")
        self.key_link.pack(fill="x", padx=8)
        self.key_link.bind("<Button-1>", lambda _e: md.open_url(PROVIDER_INFO[self.provider()]["key_url"], self))
        self.conn = ctk.CTkLabel(form, text="Connection: not tested yet", font=theme.font(13, "bold"),
                                 text_color=theme.color("muted"), anchor="w", wraplength=760, justify="left")
        self.conn.pack(fill="x", padx=8, pady=(6, 0))
        self._load_provider(active)

    def provider(self) -> str:
        return LABEL_TO_ID.get(self.provider_var.get(), "openai")

    def _load_provider(self, pid: str) -> None:
        """Show the saved model / URL / key status of the chosen provider (each provider keeps its own)."""
        info = PROVIDER_INFO[pid]
        models = list(self._live_models.get(pid) or info["models"])
        saved = settings.model_for(pid)
        if saved and saved not in models:
            models.insert(0, saved)
        self.model_box.configure(values=models or [""])
        self.model_var.set(saved)
        url = settings.base_url_for(pid)
        self.url_var.set("" if url == info["base_url"] else url)
        self.url_entry.configure(placeholder_text=info["base_url"])
        self.key_var.set("")
        self.key_entry.configure(state="normal" if info["needs_key"] or pid == "openai_compatible" else "disabled",
                                 placeholder_text="paste your API key" if info["needs_key"] else "not needed")
        self.hint.configure(text=((f"Cloud API: no model is downloaded to your computer and Ollama is not needed. "
                                   f"Default address: {info['base_url']}")
                                  if info["cloud"] else
                                  "Optional / local: uses a server on your own machine (e.g. Ollama). It is only used when you "
                                  f"select it here - the app never switches to it automatically. Default address: {info['base_url']}"))
        self.key_link.configure(text=f"Get an API key: {info['key_url']}" if info["key_url"] else "")
        self.refresh_key_info()
        self.set_connection("Connection: not tested yet", "idle")

    def refresh_key_info(self) -> None:
        pid = self.provider()
        if not PROVIDER_INFO[pid]["needs_key"] and pid != "openai_compatible":
            self.key_info.configure(text="This provider does not use an API key.")
            return
        key = secrets.get_key(pid)
        if key:
            self.key_info.configure(text=f"A key is saved ({secrets.mask(key)}), stored in: {secrets.backend_description()}. "
                                         "Leave the field empty to keep it; type a new key to replace it.")
        else:
            self.key_info.configure(text="No key saved for this provider yet. Paste it above and press Save. "
                                         f"It will be stored in: {secrets.backend_description()}.")

    def set_models(self, pid: str, models: list[str]) -> None:
        if models:
            self._live_models[pid] = models
        if pid == self.provider():
            current = self.model_var.get()
            vals = list(models or PROVIDER_INFO[pid]["models"])
            if current and current not in vals:
                vals.insert(0, current)
            self.model_box.configure(values=vals or [""])

    def set_connection(self, text: str, state: str = "idle") -> None:
        self.conn.configure(text=text, text_color=theme.color(STATE_COLOR.get(state, "muted")))

    def _refresh_models(self) -> None:
        if self.on_refresh_models:
            self.on_refresh_models(self.values())

    def _remove_key(self) -> None:
        if self.on_remove_key:
            self.on_remove_key(self.provider())

    def _save(self) -> None:
        self.on_save(self.values())

    def values(self) -> dict:
        v = {k: x.get().strip() for k, x in self.vars.items()}
        v.update({"PROVIDER": self.provider(), "MODEL": self.model_var.get().strip(), "BASE_URL": self.url_var.get().strip(),
                  "API_KEY": self.key_var.get().strip()})
        return v

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
        super().__init__(master, "User Profile", "420x390")
        self.on_save = on_save
        self.name = ctk.StringVar(value=user["name"])
        self.lang = ctk.StringVar(value=user["preferred_language"])
        self.level = ctk.StringVar(value=user["skill_level"])
        pad = dict(padx=24, anchor="w")
        ctk.CTkLabel(self, text="Display name").pack(pady=(20, 2), **pad)
        ctk.CTkEntry(self, textvariable=self.name, width=360).pack(**pad)
        ctk.CTkLabel(self, text="Language for learning notes (chat replies always follow the language you write in)",
                     wraplength=360, justify="left").pack(pady=(14, 2), **pad)
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
