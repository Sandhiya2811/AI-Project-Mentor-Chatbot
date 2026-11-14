"""Main window: wires views, background workers and the Mentor together."""
from __future__ import annotations

import logging
import queue
import shutil
import threading
from tkinter import messagebox

import customtkinter as ctk

from ai_engine.assistant import Mentor
from ai_engine.llm_provider import LLMError, get_provider, quick_health
from config import APP_NAME, UPLOAD_DIR, settings
from database import repository as repo
from interface import theme
from interface.chat_view import ChatView
from interface.project_view import HomeView, ProjectsView
from interface.resources_view import ResourcesView
from interface.settings_view import ProfileDialog, RoadmapDialog, SettingsView
from interface.sidebar import Sidebar
from learning import notes_generator
from rag import retriever

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
            "settings": SettingsView(self.host, self.save_settings, self.test_connection, self.rebuild_index),
        }
        for v in self.views.values():
            v.grid(row=0, column=0, sticky="nsew")
        self.refresh_sidebar()
        self.show_home()
        self.after(80, self._poll)
        self.run_bg(lambda: retriever.get_kb().ensure_index(), None)  # knowledge index in the background
        self.run_bg(quick_health, self._health)

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

    def _health(self, result) -> None:
        ok, msg = result
        self.views["home"].set_banner("" if ok else f"AI model not ready: {msg} (Settings > AI model). "
                                                    "Non-AI features still work.")

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
        home = self.views["home"]
        home.set_busy(True, "Analysing your idea...")
        self.run_bg(lambda: self.mentor.start_project(idea, lambda t: self.post(lambda x: home.set_busy(True, x), t)),
                    self._project_started, lambda e: (home.set_busy(False), self._unexpected(e)))

    def _project_started(self, res: dict) -> None:
        self.views["home"].reset()
        self.refresh_sidebar()
        self.open_conversation(res["conversation_id"])
        pid, lang = res["project_id"], res["language"]
        self.views["chat"].set_busy(False)
        self.run_bg(lambda: notes_generator.generate_notes(pid, lang, self.user["skill_level"]), None)

    # ---- sending messages ---------------------------------------------------------------------------
    def send(self, text: str, mode: str, paths: list[str]) -> None:
        if self.current_cid is None:
            return
        chat, cid = self.views["chat"], self.current_cid
        chat.add_message({"role": "user", "content": text or "(files attached)", "kind": "chat",
                          "metadata": {"attachments": [p.replace("\\", "/").split("/")[-1] for p in paths]}})
        chat.set_busy(True, "Reviewing your submission..." if mode == "submit" else "Thinking...")

        def done(msgs: list[dict]) -> None:
            if cid == self.current_cid:
                for m in msgs:
                    chat.add_message(m)
                project = repo.get_project(self.current_pid)
                chat.update_header(project, repo.get_progress(project["id"]), repo.get_active_task(project["id"]))
                chat.set_busy(False)
            self.refresh_sidebar()

        self.run_bg(lambda: self.mentor.chat(cid, text, mode, paths, lambda s: self.post(chat.set_status, s)), done,
                    lambda e: (chat.set_busy(False), self._unexpected(e)))

    # ---- notes / settings -----------------------------------------------------------------------
    def regenerate_notes(self, pid: int) -> None:
        v = self.views["resources"]
        conv = repo.get_conversation_for_project(pid)
        lang = self.mentor.notes_language(self.user, conv["language"] if conv else "")
        v.set_info(f"Generating notes in {lang}... this can take a minute.")

        def done(res):
            v.set_info(res["error"] and f"AI unavailable ({res['error']}) - offline notes shown." or
                       f"Generated {res['ai']} AI note(s).")
            if v.current_project_id() == pid:
                v.set_notes(repo.list_notes(pid))

        self.run_bg(lambda: notes_generator.generate_notes(
            pid, lang, self.user["skill_level"], force=True, on_progress=lambda s: self.post(v.set_info, s)), done)

    def save_settings(self, values: dict) -> None:
        old_embed = (settings.get("EMBEDDING_BACKEND"), settings.get("EMBEDDING_MODEL"))
        settings.update(values)
        theme.apply_mode(values["THEME"])
        v = self.views["settings"]
        v.set_status("Saved.")
        if (values["EMBEDDING_BACKEND"], values["EMBEDDING_MODEL"]) != old_embed:
            self.rebuild_index()
        self.run_bg(quick_health, self._health)
        self.after(200, self._rerender)

    def _rerender(self) -> None:
        """Rebuild colour-dependent widgets after a theme change."""
        if self.current_cid:
            self.open_conversation(self.current_cid)
            self._show("settings")

    def test_connection(self) -> None:
        v = self.views["settings"]
        settings.update(v.values())
        v.set_status("Testing connection...")
        self.run_bg(lambda: get_provider().ping(), lambda m: v.set_status(m),
                    lambda e: v.set_status(str(e) if isinstance(e, LLMError) else f"Error: {e}", ok=False))

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
