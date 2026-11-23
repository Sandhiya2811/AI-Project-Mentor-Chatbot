"""Main window: wires views, background workers and the Mentor together."""
from __future__ import annotations

import logging
import queue
import shutil
import threading
from tkinter import messagebox

import customtkinter as ctk

from ai_engine.assistant import Mentor
from ai_engine.llm_provider import LLMError, build_provider, connection_status, get_provider, quick_health
from config import APP_NAME, PROVIDER_INFO, UPLOAD_DIR, settings
from database import repository as repo
from interface import theme
from interface.chat_view import ChatView
from interface.project_view import HomeView, ProjectsView
from interface.resources_view import ResourcesView
from interface.settings_view import ProfileDialog, RoadmapDialog, SettingsView
from interface.sidebar import Sidebar
from learning import notes_generator
from rag import retriever
from utils import secrets

log = logging.getLogger(__name__)


class App(ctk.CTk):
    def __init__(self) -> None:
        theme.apply_mode(settings.get("THEME"))
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1320x820")
        self.minsize(1000, 640)
        self.mentor = Mentor()
        self.user = repo.get_user()
        self.current_cid: int | None = None
        self.current_pid: int | None = None
        self.search_query = ""
        self._notes_cancel: threading.Event | None = None   # stops AI note generation so chat always has priority
        self._notes_job = None
        self._q: queue.Queue = queue.Queue()
        self._view = "home"

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.sidebar = Sidebar(self, {
            "new_chat": self.show_home, "search": self._search, "projects": self.show_projects,
            "resources": lambda: self.show_resources(self.current_pid), "settings": self.show_settings,
            "profile": self.show_profile, "clear_history": self.clear_history},
            (self.open_conversation, self.rename_conversation, self.delete_conversation))
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.host = ctk.CTkFrame(self, fg_color=theme.color("bg"), corner_radius=0)
        self.host.grid(row=0, column=1, sticky="nsew")
        self.host.grid_columnconfigure(0, weight=1)
        self.host.grid_rowconfigure(0, weight=1)
        self.views = {
            "home": HomeView(self.host, self.start_project),
            "chat": ChatView(self.host, self.send, self.show_home, self.show_roadmap),
            "projects": ProjectsView(self.host, self.resume_project, self.delete_project, self.show_resources),
            "resources": ResourcesView(self.host, lambda pid: self.show_resources(pid), self.regenerate_notes),
            "settings": SettingsView(self.host, self.save_settings, self.test_connection, self.rebuild_index,
                                     self.refresh_models, self.remove_key),
        }
        for v in self.views.values():
            v.grid(row=0, column=0, sticky="nsew")
        self.refresh_sidebar()
        self.show_home()
        self.after(80, self._poll)
        self.run_bg(lambda: retriever.get_kb().ensure_index(), None)  # knowledge index in the background
        secrets.migrate_legacy()                       # old plain-text key -> OS keyring (only if a keyring exists)
        self.run_bg(self._check_provider, self._health)

    # ---- background work -----------------------------------------------------------------------
    def run_bg(self, fn, on_ok=None, on_err=None) -> None:
        def worker():
            try:
                self._q.put((on_ok, fn()))
            except Exception as exc:  # surfaced on the UI thread
                log.exception("Background task failed")
                self._q.put((on_err or self._unexpected, exc))
        threading.Thread(target=worker, daemon=True).start()

    def post(self, fn, arg) -> None:
        self._q.put((fn, arg))

    def _poll(self) -> None:
        try:
            while True:
                cb, arg = self._q.get_nowait()
                if cb:
                    cb(arg)
        except queue.Empty:
            pass
        self.after(80, self._poll)

    def _unexpected(self, exc: Exception) -> None:
        self.views["chat"].set_busy(False)
        self.views["home"].set_busy(False)
        messagebox.showerror(APP_NAME, f"Something went wrong:\n{exc}")

    @staticmethod
    def _check_provider() -> tuple[bool, str]:
        """Start-up / after-save check: config first (no network), then the provider's API (no tokens spent)."""
        ok, msg = quick_health()
        if not ok:
            return ok, msg
        ok, msg = connection_status()
        if ok:
            try:
                get_provider().warm_up()           # Ollama only: load the model; cloud providers do nothing
            except LLMError:
                pass
        return ok, msg

    def _health(self, result) -> None:
        ok, msg = result
        label = PROVIDER_INFO.get(settings.active_provider, {}).get("label", settings.active_provider)
        self.views["home"].set_banner(f"AI connected: {label} - {settings.model_for(settings.active_provider)}" if ok else
                                      f"AI model not ready: {msg}  (Settings > AI model). Non-AI features still work.", ok)
        v = self.views["settings"]
        if v.provider() == settings.active_provider:
            v.set_connection(("Connection: OK - " if ok else "Connection problem - ") + msg, "ok" if ok else "bad")

    @staticmethod
    def _warm_up() -> None:
        get_provider().warm_up()

    # ---- navigation ------------------------------------------------------------------------------
    def _show(self, name: str) -> None:
        self._view = name
        self.views[name].tkraise()

    def show_home(self) -> None:
        self.current_cid = None
        self.views["home"].reset()
        self._show("home")
        self.refresh_sidebar()

    def show_projects(self) -> None:
        self.views["projects"].set_projects(repo.list_projects(self.user["id"]))
        self._show("projects")

    def show_resources(self, pid: int | None = None) -> None:
        projects = repo.list_projects(self.user["id"])
        pid = pid or self.current_pid or (projects[0]["id"] if projects else None)
        v = self.views["resources"]
        v.set_projects(projects, pid)
        if pid:
            self.current_pid = pid
            notes = repo.list_notes(pid)
            v.set_notes(notes)
            offline = sum(1 for n in notes if n["source"] != "llm")
            v.set_info(f"{len(notes)} note(s)" + (f" - {offline} offline (AI was unavailable); press Regenerate."
                                                  if offline else "") if notes else
                       "Notes are prepared right after a project starts.")
        else:
            v.set_notes([])
            v.set_info("Start a project to get personalised notes.")
        self._show("resources")

    def show_settings(self) -> None:
        self._show("settings")

    def show_profile(self) -> None:
        ProfileDialog(self, self.user, self._save_profile)

    def _save_profile(self, name, lang, level) -> None:
        repo.update_user(self.user["id"], name=name, preferred_language=lang, skill_level=level)
        self.user = repo.get_user()

    def show_roadmap(self) -> None:
        if self.current_pid:
            RoadmapDialog(self, repo.get_project(self.current_pid), repo.list_tasks(self.current_pid))

    # ---- sidebar / history -----------------------------------------------------------------------
    def refresh_sidebar(self) -> None:
        self.sidebar.history.set_items(repo.list_conversations(self.user["id"], self.search_query), self.current_cid)

    def _search(self, query: str) -> None:
        self.search_query = query
        self.refresh_sidebar()

    def rename_conversation(self, cid: int, old: str) -> None:
        new = ctk.CTkInputDialog(text="New conversation name:", title="Rename conversation").get_input()
        if new and new.strip():
            repo.rename_conversation(cid, new.strip())
            self.refresh_sidebar()

    def delete_conversation(self, cid: int) -> None:
        if messagebox.askyesno(APP_NAME, "Delete this conversation?\nThe project, its tasks and your submissions are kept "
                                         "and can be resumed from Previous Projects."):
            repo.delete_conversation(cid)
            if cid == self.current_cid:
                self.show_home()
            self.refresh_sidebar()

    def clear_history(self) -> None:
        if messagebox.askyesno(APP_NAME, "Delete ALL conversations?\nProjects, progress and submissions are kept; you can "
                                         "resume any project from Previous Projects."):
            repo.clear_all_conversations(self.user["id"])
            self.show_home()

    # ---- conversations ---------------------------------------------------------------------------
    def open_conversation(self, cid: int) -> None:
        conv = repo.get_conversation(cid)
        if not conv:
            return
        self.current_cid, self.current_pid = cid, conv["project_id"]
        project = repo.get_project(conv["project_id"])
        self.views["chat"].load(project, repo.list_messages(cid), repo.get_progress(project["id"]),
                                repo.get_active_task(project["id"]))
        self._show("chat")
        self.refresh_sidebar()

    def resume_project(self, pid: int) -> None:
        self.open_conversation(self.mentor.resume_project(pid))

    def delete_project(self, pid: int, title: str) -> None:
        if messagebox.askyesno(APP_NAME, f"Permanently delete project '{title}' with all its tasks, submissions, "
                                         "notes and conversation?"):
            repo.delete_project(pid)
            shutil.rmtree(UPLOAD_DIR / str(pid), ignore_errors=True)
            if pid == self.current_pid:
                self.current_pid = self.current_cid = None
            self.refresh_sidebar()
            self.show_projects()

    # ---- starting a project ---------------------------------------------------------------------
    def start_project(self, idea: str) -> None:
        home, chat = self.views["home"], self.views["chat"]
        home.set_busy(True, "Analysing your idea...")
        self._stop_notes()

        def created(info: dict) -> None:       # the project exists: open the chat and let the intro stream in
            home.reset()
            self.refresh_sidebar()
            self.open_conversation(info["conversation_id"])
            chat.set_busy(True, "Writing your first task...")

        self.run_bg(lambda: self.mentor.start_project(
            idea, lambda t: self.post(lambda x: home.set_busy(True, x), t),
            on_created=lambda info: self.post(created, info), on_token=lambda t: self.post(chat.stream_append, t)),
            self._project_started, lambda e: (home.set_busy(False), chat.drop_stream(), chat.set_busy(False),
                                              self._unexpected(e)))

    def _project_started(self, res: dict) -> None:
        chat = self.views["chat"]
        if self.current_cid == res["conversation_id"]:
            chat.finish_stream(res["message"])
        chat.set_busy(False)
        self.refresh_sidebar()
        self._schedule_notes(res["project_id"], res["language"])

    # ---- AI learning notes run only when the student is idle (they would compete with chat for the model) -----------
    def _schedule_notes(self, pid: int | None, lang: str, delay_ms: int = 40000) -> None:
        if self._notes_job is not None:
            self.after_cancel(self._notes_job)
        if pid and settings.get("AUTO_AI_NOTES") != "off":
            self._notes_job = self.after(delay_ms, lambda: self._start_notes(pid, lang))

    def _start_notes(self, pid: int, lang: str, force: bool = False, on_done=None) -> None:
        self._notes_job = None
        self._stop_notes()
        cancel = self._notes_cancel = threading.Event()
        skill = self.user["skill_level"]
        self.run_bg(lambda: notes_generator.generate_notes(pid, lang, skill, force=force, cancel=cancel,
                                                           on_progress=lambda s: self.post(self._notes_progress, (pid, s))),
                    on_done or self._notes_done)

    def _stop_notes(self) -> None:
        if self._notes_job is not None:
            self.after_cancel(self._notes_job)
            self._notes_job = None
        if self._notes_cancel is not None:
            self._notes_cancel.set()

    def _notes_progress(self, arg) -> None:
        pid, text = arg
        if self._view == "resources" and self.views["resources"].current_project_id() == pid:
            self.views["resources"].set_info(text)

    def _notes_done(self, res: dict) -> None:
        v = self.views["resources"]
        pid = v.current_project_id()
        if self._view == "resources" and pid:
            v.set_notes(repo.list_notes(pid))
            v.set_info("Paused while you were chatting - it resumes automatically when you are idle." if res.get("cancelled")
                       else (f"AI unavailable ({res['error']}) - offline notes with official links are shown." if res.get("error")
                             else f"{res['ai']} AI note(s) written."))

    # ---- sending messages ---------------------------------------------------------------------------
    def send(self, text: str, mode: str, paths: list[str]) -> None:
        if self.current_cid is None:
            return
        chat, cid, pid = self.views["chat"], self.current_cid, self.current_pid
        self._stop_notes()                                    # the chat gets the model first
        chat.add_message({"role": "user", "content": text or "(files attached)", "kind": "chat",
                          "metadata": {"attachments": [p.replace("\\", "/").split("/")[-1] for p in paths]}})
        chat.set_busy(True, "Reviewing your submission..." if mode == "submit" else "Thinking...")

        def on_token(t: str) -> None:                         # streamed pieces of the answer (worker thread -> UI thread)
            self.post(lambda x: chat.stream_append(x) if cid == self.current_cid else None, t)

        def done(msgs: list[dict]) -> None:
            if cid == self.current_cid:
                for m in msgs:
                    (chat.finish_stream if m is msgs[0] else chat.add_message)(m)
                project = repo.get_project(self.current_pid)
                chat.update_header(project, repo.get_progress(project["id"]), repo.get_active_task(project["id"]))
                chat.set_busy(False)
            self.refresh_sidebar()
            conv = repo.get_conversation(cid)
            self._schedule_notes(pid, self.mentor.notes_language(self.user, conv["language"] if conv else ""))

        self.run_bg(lambda: self.mentor.chat(cid, text, mode, paths, lambda s: self.post(chat.set_status, s), on_token),
                    done, lambda e: (chat.drop_stream(), chat.set_busy(False), self._unexpected(e)))

    # ---- notes / settings -----------------------------------------------------------------------
    def regenerate_notes(self, pid: int) -> None:
        v = self.views["resources"]
        conv = repo.get_conversation_for_project(pid)
        lang = self.mentor.notes_language(self.user, conv["language"] if conv else "")
        v.set_info(f"Generating notes in {lang}... they appear as they finish (chatting pauses this).")
        self._start_notes(pid, lang, force=True, on_done=self._notes_done)

    def save_settings(self, values: dict) -> None:
        old_embed = (settings.get("EMBEDDING_BACKEND"), settings.get("EMBEDDING_MODEL"))
        p = values["PROVIDER"]
        P = p.upper()
        model = values["MODEL"] or PROVIDER_INFO[p]["model"]
        url = values["BASE_URL"]
        settings.update({k: values[k] for k in ("THEME", "EMBEDDING_BACKEND", "EMBEDDING_MODEL", "CODE_EXECUTION")} | {
            "LLM_PROVIDER": p, "LLM_MODEL": model, f"MODEL_{P}": model, "LLM_BASE_URL": url, f"BASE_URL_{P}": url})
        theme.apply_mode(values["THEME"])
        v = self.views["settings"]
        msg = "Saved."
        if values["API_KEY"]:
            where = secrets.set_key(p, values["API_KEY"])       # never written to .env, logs or the database
            msg += f" API key stored in: {where}."
            v.key_var.set("")
        v.refresh_key_info()
        v.set_status(msg)
        if (values["EMBEDDING_BACKEND"], values["EMBEDDING_MODEL"]) != old_embed:
            self.rebuild_index()
        v.set_connection("Connection: checking...", "busy")
        self.run_bg(self._check_provider, self._health)
        self.after(200, self._rerender)

    def _rerender(self) -> None:
        """Rebuild colour-dependent widgets after a theme change."""
        if self.current_cid:
            self.open_conversation(self.current_cid)
            self._show("settings")

    @staticmethod
    def _provider_from_form(values: dict):
        """A provider built from what is typed in the form (nothing is saved by testing)."""
        p = values["PROVIDER"]
        return build_provider(p, values["MODEL"] or settings.model_for(p), values["BASE_URL"] or PROVIDER_INFO[p]["base_url"],
                              values["API_KEY"] or settings.api_key_for(p))

    def test_connection(self, values: dict | None = None) -> None:
        v = self.views["settings"]
        values = values or v.values()
        p = values["PROVIDER"]
        v.set_connection("Connection: testing...", "busy")

        def work():
            prov = self._provider_from_form(values)
            ok, msg = prov.validate()
            models = []
            if ok:
                try:
                    models = prov.list_models()
                except LLMError:
                    models = []
            return ok, msg, models

        def done(res):
            ok, msg, models = res
            v.set_connection(("Connection OK - " if ok else "Connection failed - ") + msg, "ok" if ok else "bad")
            if models:
                v.set_models(p, models)

        self.run_bg(work, done, lambda e: v.set_connection(f"Connection failed - {secrets.redact(str(e))}", "bad"))

    def refresh_models(self, values: dict | None = None) -> None:
        v = self.views["settings"]
        values = values or v.values()
        p = values["PROVIDER"]
        v.set_connection("Fetching the list of models...", "busy")

        def done(models):
            if models:
                v.set_models(p, models)
                v.set_connection(f"Connection OK - {len(models)} model(s) available for this account.", "ok")
            else:
                v.set_connection("This provider does not offer a model list - choose from the built-in list or type a model name.", "idle")

        self.run_bg(lambda: self._provider_from_form(values).list_models(), done,
                    lambda e: v.set_connection(f"Could not fetch models - {secrets.redact(str(e))}", "bad"))

    def remove_key(self, provider: str) -> None:
        if messagebox.askyesno(APP_NAME, f"Remove the saved API key for {PROVIDER_INFO[provider]['label']}?"):
            secrets.delete_key(provider)
            v = self.views["settings"]
            v.refresh_key_info()
            v.set_connection("Key removed.", "idle")
            if provider == settings.active_provider:
                self.run_bg(self._check_provider, self._health)

    def rebuild_index(self) -> None:
        v = self.views["settings"]
        v.set_status("Rebuilding knowledge index...")
        retriever.reset_kb()

        def work():
            kb = retriever.get_kb()
            kb.ensure_index(force=True)
            return kb
        self.run_bg(work, lambda kb: v.set_status(f"Knowledge base ready: {len(kb.chunks)} chunks ({kb.embedder.signature})."
                                                  if kb.ready else f"Index failed: {kb.error}", ok=kb.ready))
