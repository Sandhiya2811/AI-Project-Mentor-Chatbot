"""The Mentor: the single entry point the UI talks to. Orchestrates LLM, RAG, guard, review and progress."""
from __future__ import annotations

import logging
import shutil
import tempfile
import time
from pathlib import Path

from ai_engine import prompts
from ai_engine.conversation_memory import build_history
from ai_engine.language_detector import LangInfo, detect, reply_language_instruction
from ai_engine.llm_provider import LLMError, get_provider
from ai_engine.response_guard import check as guard_check
from code_review import review_engine
from database import repository as repo
from project_manager import idea_analyzer, roadmap_generator, task_manager
from rag import retriever
from utils.helpers import short_title, truncate

log = logging.getLogger(__name__)
UNAVAILABLE_HELP = ("The AI model is not available right now ({err}).\n\nWhat still works: browsing your projects and "
                    "history, Learning Resources, and rule-based review of submissions (use Submit for review). "
                    "Fix the connection in Settings and try again.")


class Mentor:
    # ---- helpers --------------------------------------------------------------------------
    @staticmethod
    def language_rule(text: str, user: dict, fallback_lang: str = "") -> tuple[str, LangInfo]:
        info = detect(text) if text.strip() else LangInfo(fallback_lang or "unknown", "unknown", False)
        return reply_language_instruction(info, user["preferred_language"]), info

    @staticmethod
    def notes_language(user: dict, conv_language: str) -> str:
        if user["preferred_language"] != "Auto-detect":
            return user["preferred_language"]
        if not conv_language or conv_language.lower().startswith(("english", "unknown")):
            return "English"
        return conv_language

    def _llm_text(self, system: str, user: str, max_tokens: int = 2500) -> str:
        """One guarded generation. Raises LLMError."""
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        llm = get_provider()
        reply = llm.chat(msgs, temperature=0.4, max_tokens=max_tokens)
        res = guard_check(reply)
        if not res.ok:
            reply = llm.chat(msgs + [{"role": "assistant", "content": reply},
                                     {"role": "user", "content": prompts.STRICTER_REMINDER}],
                             temperature=0.3, max_tokens=max_tokens)
            res = guard_check(reply)
        return res.text.strip()

    # ---- starting / resuming a project --------------------------------------------------------
    def start_project(self, idea: str, on_status=None) -> dict:
        say = on_status or (lambda s: None)
        user = repo.get_user()
        rule, info = self.language_rule(idea, user)
        source, err = "llm", ""
        say("Understanding your project idea...")
        try:
            analysis = idea_analyzer.analyze(idea, user["skill_level"])
            say("Designing your personalised roadmap...")
            tasks = roadmap_generator.generate(analysis, user["skill_level"])
        except LLMError as exc:
            err, source = str(exc), "template"
            analysis = idea_analyzer.fallback_analysis(idea)
            tasks = roadmap_generator.template_roadmap(analysis)
        pid = repo.create_project(user["id"], analysis["title"], idea, analysis["objective"], analysis["domain"],
                                  analysis["programming_language"], analysis["difficulty"], source,
                                  analysis["tools"], analysis["requirements"], tasks)
        cid = repo.create_conversation(user["id"], pid, short_title(analysis["title"], 40), info.name)
        repo.add_message(cid, "user", idea)
        say("Writing your first task...")
        project, tasks_db = repo.get_project(pid), repo.list_tasks(pid)
        if source == "template":
            repo.add_message(cid, "system", UNAVAILABLE_HELP.format(err=err) +
                             "\n\nA generic template roadmap was created instead of an AI-designed one. "
                             "Start a new project once the model is reachable for a personalised plan.", kind="notice")
        repo.add_message(cid, "assistant", self._intro(project, tasks_db, rule, source == "template"))
        repo.log_activity(user["id"], pid, "project_started", analysis["title"])
        return {"conversation_id": cid, "project_id": pid, "source": source, "error": err,
                "language": self.notes_language(user, info.name)}

    def _intro(self, project: dict, tasks: list[dict], rule: str, template: bool) -> str:
        t1 = tasks[0]
        try:
            return self._llm_text(
                prompts.system_prompt("new student", project["title"], task_manager.describe_task(t1), "", "", rule),
                prompts.INTRO_PROMPT.format(
                    language_rule=rule, title=project["title"], objective=project["objective"],
                    stages="; ".join(f"{t['position']}. {t['title']}" for t in tasks), t1_title=t1["title"],
                    t1_desc=t1["description"], t1_out=t1["expected_output"],
                    notice=prompts.SUMMARY_NOTICE_TEMPLATE if template else ""))
        except LLMError:
            stages = "\n".join(f"{t['position']}. {t['title']}" for t in tasks)
            return (f"Let's build your project: {project['title']}.\n\n**Project Objective:** {project['objective']}\n\n"
                    f"We will complete these stages one by one:\n{stages}\n\n"
                    f"## Task 1: {t1['title']}\n{t1['description']}\n\n**Expected output:** {t1['expected_output']}\n\n"
                    "Complete it, then use **Submit for review** (attach files or type your answer).")

    def resume_project(self, project_id: int) -> int:
        conv = repo.get_conversation_for_project(project_id)
        if conv:
            return conv["id"]
        user, project = repo.get_user(), repo.get_project(project_id)
        cid = repo.create_conversation(user["id"], project_id, short_title(project["title"], 40))
        task, prog = repo.get_active_task(project_id), repo.get_progress(project_id)
        body = (f"Welcome back to **{project['title']}**. Progress: {prog['completed_tasks']}/{prog['total_tasks']} tasks "
                f"({prog['percent']:.0f}%).\n\n")
        if task:
            body += (f"## Current task {task['position']}: {task['title']}\n{task['description']}\n\n"
                     f"**Expected output:** {task['expected_output']}\n\nSubmit it when ready, or ask me anything about it.")
        else:
            body += "This project is complete. You can still ask me questions about it."
        repo.add_message(cid, "assistant", body)
        return cid

    # ---- chat ------------------------------------------------------------------------------------
    def chat(self, conversation_id: int, text: str, mode: str = "ask", paths: list[str] | None = None,
             on_status=None) -> list[dict]:
        """Stores the student's message, produces and stores the mentor's reply/replies, returns the new messages."""
        say = on_status or (lambda s: None)
        conv = repo.get_conversation(conversation_id)
        project = repo.get_project(conv["project_id"])
        user = repo.get_user()
        rule, info = self.language_rule(text, user, conv.get("language", ""))
        if info.name != "unknown":
            repo.set_conversation_language(conversation_id, info.name)
        paths = [Path(p) for p in (paths or [])]
        meta = {"attachments": [p.name for p in paths], "mode": "submit" if (mode == "submit" or paths) else "ask"}
        repo.add_message(conversation_id, "user", text or "(files attached)", metadata=meta)
        if meta["mode"] == "submit":
            return self._submission(conversation_id, project, user, text, paths, rule, say)
        return self._question(conversation_id, project, user, text, rule, say)

    def _question(self, cid, project, user, text, rule, say) -> list[dict]:
        say("Thinking...")
        pid = project["id"]
        task, tasks = repo.get_active_task(pid), repo.list_tasks(pid)
        report = repo.latest_report(task["id"]) if task else None
        last_review = truncate(report["report_md"], 1400) if report else ""
        query = f"{project['title']} {task['title'] if task else ''} {text}"
        chunks = retriever.retrieve(query, project, tasks, repo.list_requirements(pid))
        system = prompts.system_prompt(
            f"{user['name']} (skill level: {user['skill_level']})",
            f"{project['title']} - {project['objective']} (language: {project['programming_language']}, "
            f"{'completed' if project['status'] == 'completed' else 'in progress'})",
            task_manager.describe_task(task), last_review, retriever.format_chunks(chunks), rule)
        msgs = [{"role": "system", "content": system}] + build_history(cid)
        try:
            llm = get_provider()
            reply = llm.chat(msgs, max_tokens=2500).strip()
            violations: list[str] = []
            if reply.startswith(prompts.OFF_TOPIC_TOKEN) or prompts.OFF_TOPIC_TOKEN in reply[:40]:
                reply = prompts.OFF_TOPIC_REPLY
            else:
                res = guard_check(reply)
                if not res.ok:
                    violations = res.violations
                    say("Re-checking my answer against the no-code policy...")
                    retry = llm.chat(msgs + [{"role": "assistant", "content": reply},
                                             {"role": "user", "content": prompts.STRICTER_REMINDER}],
                                     temperature=0.3, max_tokens=2500)
                    res = guard_check(retry)
                reply = res.text.strip()
            if not reply:
                raise LLMError("The model returned an empty answer.")
            return [repo.add_message(cid, "assistant", reply, metadata={"guard_violations": violations})]
        except LLMError as exc:
            return [repo.add_message(cid, "system", UNAVAILABLE_HELP.format(err=exc), kind="notice")]

    def _submission(self, cid, project, user, text, paths, rule, say) -> list[dict]:
        task = repo.get_active_task(project["id"])
        if not task:
            return [repo.add_message(cid, "assistant", "This project is already complete - there is nothing left to submit. "
                                                       "Ask me anything about it, or start a new project.")]
        staging = None
        if not paths:
            if len(text.split()) < 3:
                return [repo.add_message(cid, "assistant", "Attach your files with the Upload button, or type your answer, "
                                                           "then press Send in Submit mode.")]
            staging = Path(tempfile.mkdtemp(prefix="mentor_answer_"))
            (staging / "answer.md").write_text(text, encoding="utf-8")
            paths = [staging / "answer.md"]
        try:
            outcome = review_engine.review(project, task, paths, text, rule, say)
        except Exception as exc:  # unexpected - never crash the UI
            log.exception("Review failed")
            return [repo.add_message(cid, "system", f"The review could not be completed: {exc}", kind="notice")]
        finally:
            if staging:
                shutil.rmtree(staging, ignore_errors=True)
        out = [repo.add_message(cid, "assistant", outcome.report_md, kind="review",
                                metadata={"status": outcome.status, "submission_id": outcome.submission_id})]
        if outcome.passed:
            say("Preparing what comes next...")
            out.append(repo.add_message(cid, "assistant", self._after_pass(project, outcome, rule)))
        return out

    def _after_pass(self, project: dict, outcome, rule: str) -> str:
        tasks = repo.list_tasks(project["id"])
        try:
            if outcome.project_done:
                return self._llm_text(
                    prompts.system_prompt("student", project["title"], "none - project complete", "", "", rule),
                    prompts.COMPLETION_PROMPT.format(title=project["title"], language_rule=rule,
                                                     stages=task_manager.roadmap_summary(tasks)))
            nt = outcome.next_task
            return self._llm_text(
                prompts.system_prompt("student", project["title"], task_manager.describe_task(nt), "", "", rule),
                prompts.NEXT_TASK_PROMPT.format(language_rule=rule, n=nt["position"], title=nt["title"],
                                                desc=nt["description"], out=nt["expected_output"],
                                                hints="; ".join(nt["hints"]) or "none"))
        except LLMError:
            if outcome.project_done:
                return f"Congratulations - **{project['title']}** is complete and fully validated!"
            nt = outcome.next_task
            return (f"## Task {nt['position']}: {nt['title']}\n{nt['description']}\n\n"
                    f"**Expected output:** {nt['expected_output']}\n\nSubmit it when ready.")
