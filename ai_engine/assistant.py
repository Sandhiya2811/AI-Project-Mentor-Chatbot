"""The Mentor: the single entry point the UI talks to. Orchestrates LLM, RAG, guard, review and progress.

Conversation flow for a normal message (see `_question`):
  1. intent_router.classify()  - what does the student want? (no LLM call, microseconds)
  2. unrelated?               -> fixed polite reply, no LLM at all
  3. _plan()                  - turns the intent + REAL project/task state into a directive and the facts the LLM needs
  4. RAG only for concept/error/follow-up questions (workflow questions are answered from the roadmap itself)
  5. streaming generation through StreamGuard (no-code policy) + URL filter; first words are shown immediately
  6. final guard pass, verified-link block appended by the application, message stored with timings

Nothing in this module can mark a task as passed: only review_engine (rule checks + AI review) can.
"""
from __future__ import annotations

import logging
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from ai_engine import intent_router, prompts
from ai_engine.conversation_memory import build_history
from ai_engine.language_detector import LangInfo, detect, reply_language_instruction, resolve
from ai_engine.llm_provider import LLMError, get_provider
from ai_engine.response_guard import StreamGuard
from ai_engine.response_guard import check as guard_check
from code_review import review_engine
from config import settings
from database import repository as repo
from learning import notes_generator, resource_manager
from project_manager import idea_analyzer, roadmap_generator, task_manager
from rag import retriever
from utils.helpers import loads, short_title

log = logging.getLogger(__name__)
UNAVAILABLE_HELP = ("The AI model is not available right now ({err}).\n\nWhat still works: browsing your projects and "
                    "history, Learning Resources, and rule-based review of submissions (use Submit for review). "
                    "Fix the connection in Settings and try again.")
OFFLINE_PREFIX = "(The AI model is unavailable, so this answer comes directly from your saved roadmap.)\n\n"
STATUS_LABEL = {"passed": "Completed", "active": "Current", "locked": "Locked"}
MAX_TOKENS = {"acknowledge": 220, "whats_next": 450, "advance": 600, "completion": 450, "explain_task": 800,
              "explain_roadmap": 1500, "tools": 900, "resources": 900, "concept": 700, "error": 800, "followup": 600,
              "ambiguous": 600}

# ---- verified-URL safety -------------------------------------------------------------------------------------------
_URL = re.compile(r"https?://[^\s<>\]\)\"']+")


def _allowed_urls() -> set[str]:
    urls: set[str] = set()
    for e in resource_manager.CATALOG.values():
        urls.add(e.official[1])
        urls.update(u for _t, u, _s in e.links)
    return urls


def sanitize_urls(text: str, allowed: set[str] | None = None) -> str:
    """Remove every URL that is not in the curated catalog (an LLM must never invent a link)."""
    allowed = allowed if allowed is not None else _allowed_urls()

    def fix(m: re.Match) -> str:
        url = m.group(0)
        core = url.rstrip(".,;:!?")
        return url if core in allowed else "[unverified link removed]" + url[len(core):]
    return _URL.sub(fix, text)


class _UrlFilter:
    """Streaming version of sanitize_urls: holds back only the last (possibly unfinished) word."""

    def __init__(self) -> None:
        self.buf, self.allowed = "", _allowed_urls()

    def feed(self, text: str) -> str:
        self.buf += text
        i = max(self.buf.rfind(" "), self.buf.rfind("\n"))
        if i < 0:
            return ""
        head, self.buf = self.buf[: i + 1], self.buf[i + 1:]
        return sanitize_urls(head, self.allowed)

    def finish(self) -> str:
        out, self.buf = sanitize_urls(self.buf, self.allowed), ""
        return out


@dataclass
class Plan:
    """What to tell the LLM (and what to say if the LLM is unavailable) for one message."""
    directive: str
    details: str = "(none)"
    max_tokens: int = 700
    append: str = ""          # deterministic block (verified links) added after the model's answer
    fallback: str = ""        # deterministic answer used when the LLM cannot be reached
    intro_task: int | None = None   # task whose (re)introduction this reply is


def _noop(*_a, **_k) -> None:
    return None


class Mentor:
    # ---- language -----------------------------------------------------------------------------------------------
    @staticmethod
    def language_rule(text: str, user: dict, fallback_lang: str = "") -> tuple[str, LangInfo]:
        """Language is decided per message (never from a setting). `user` is kept for API compatibility.
        Tiny follow-ups ('ok', 'next task') keep the language of the conversation; a clear switch is followed at once."""
        recent = "" if (not fallback_lang or fallback_lang.lower().startswith(("english", "unknown"))) else fallback_lang
        info = resolve(text, recent) if text.strip() else LangInfo(fallback_lang or "unknown", "unknown", False)
        return reply_language_instruction(info, "", recent), info

    @staticmethod
    def notes_language(user: dict, conv_language: str) -> str:
        if user["preferred_language"] != "Auto-detect":
            return user["preferred_language"]
        if not conv_language or conv_language.lower().startswith(("english", "unknown")):
            return "English"
        return conv_language

    # ---- generation helpers ---------------------------------------------------------------------------------------
    def _llm_text(self, system: str, user: str, max_tokens: int = 900) -> str:
        """One guarded, non-streaming generation (used for short post-review messages). Raises LLMError."""
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        llm = get_provider()
        reply = llm.chat(msgs, temperature=0.4, max_tokens=max_tokens)
        res = guard_check(reply)
        if not res.ok:
            reply = llm.chat(msgs + [{"role": "assistant", "content": reply},
                                     {"role": "user", "content": prompts.STRICTER_REMINDER}],
                             temperature=0.3, max_tokens=max_tokens)
            res = guard_check(reply)
        return sanitize_urls(res.text.strip())

    def _stream(self, msgs: list[dict], max_tokens: int, on_token, allow_off_topic: bool = False, cancel=None):
        """Stream a reply to the UI through the no-code guard and the URL filter.

        Returns (final_text, violations, off_topic, stats). The final text comes from a complete guard pass, so it can
        be slightly stricter than what streamed (e.g. unfenced code); the UI swaps it in when the stream ends.
        """
        llm = get_provider()
        sg, uf, raw, decided = StreamGuard(), _UrlFilter(), "", not allow_off_topic
        token, off = prompts.OFF_TOPIC_TOKEN, False

        def emit(chunk: str) -> None:
            out = uf.feed(sg.feed(chunk))
            if out:
                on_token(out)

        for piece in llm.stream_chat(msgs, max_tokens=max_tokens, cancel=cancel):
            raw += piece
            if not decided:
                probe = raw.lstrip()
                if probe.startswith(token):
                    off = True
                    break
                if len(probe) >= len(token) or not token.startswith(probe):
                    decided = True
                    emit(raw)
                continue
            emit(piece)
        if off:
            return prompts.OFF_TOPIC_REPLY, [], True, dict(getattr(llm, "last_stats", {}) or {})
        if not decided and raw:
            emit(raw)
        tail = uf.feed(sg.finish()) + uf.finish()
        if tail:
            on_token(tail)
        res = guard_check(raw)
        return sanitize_urls(res.text.strip()), res.violations, False, dict(getattr(llm, "last_stats", {}) or {})

    # ---- starting / resuming a project --------------------------------------------------------------------------
    def start_project(self, idea: str, on_status=None, on_created=None, on_token=None) -> dict:
        """on_created(info) fires as soon as the project exists (the UI can open the chat); on_token streams the
        opening message. Both are optional, so the old call `start_project(idea, on_status)` still works."""
        say, on_created, on_token = on_status or _noop, on_created or _noop, on_token or _noop
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
        if source == "template":
            repo.add_message(cid, "system", UNAVAILABLE_HELP.format(err=err) +
                             "\n\nA generic template roadmap was created instead of an AI-designed one. "
                             "Start a new project once the model is reachable for a personalised plan.", kind="notice")
        try:  # offline learning notes + official links exist immediately, no LLM involved
            notes_generator.ensure_base_notes(pid)
        except Exception:
            log.exception("Could not create the offline learning notes")
        language = self.notes_language(user, info.name)
        on_created({"conversation_id": cid, "project_id": pid, "source": source, "error": err, "language": language})
        say("Writing your first task...")
        project, tasks_db = repo.get_project(pid), repo.list_tasks(pid)
        tools = repo.list_requirements(pid, "tool")
        text = self._intro(project, tasks_db, rule, source == "template", on_token)
        block = "\n\n" + resource_manager.chat_block(tools, tasks_db)   # tools + official learning links, deterministic
        on_token(block)
        msg = repo.add_message(cid, "assistant", text + block, metadata={"intro_task": tasks_db[0]["id"], "intent": "intro"})
        repo.log_activity(user["id"], pid, "project_started", analysis["title"])
        return {"conversation_id": cid, "project_id": pid, "source": source, "error": err, "language": language,
                "message": msg}

    def _intro(self, project: dict, tasks: list[dict], rule: str, template: bool, on_token) -> str:
        t1 = tasks[0]
        system = prompts.system_prompt("new student", project["title"], task_manager.describe_task(t1), "", "", rule,
                                       roadmap=self._roadmap_text(tasks), allow_off_topic=False)
        user_msg = prompts.INTRO_PROMPT.format(
            language_rule=rule, title=project["title"], objective=project["objective"],
            stages="; ".join(f"{t['position']}. {t['title']}" for t in tasks), t1_title=t1["title"],
            t1_desc=t1["description"], t1_out=t1["expected_output"],
            notice=prompts.SUMMARY_NOTICE_TEMPLATE if template else "")
        try:
            text, _v, _off, stats = self._stream([{"role": "system", "content": system},
                                                  {"role": "user", "content": user_msg}], 1000, on_token)
            log.info("intro generated: %s", self._fmt_stats(stats))
            if text:
                return text
        except LLMError:
            pass
        stages = "\n".join(f"{t['position']}. {t['title']}" for t in tasks)
        text = (f"Let's build your project: {project['title']}.\n\n**Project Objective:** {project['objective']}\n\n"
                f"We will complete these stages one by one:\n{stages}\n\n"
                f"## Task 1: {t1['title']}\n{t1['description']}\n\n**Expected output:** {t1['expected_output']}\n\n"
                "Complete it, then use **Submit for review** (attach files or type your answer).")
        on_token(text)
        return text

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
             on_status=None, on_token=None, cancel=None) -> list[dict]:
        """Stores the student's message, produces and stores the mentor's reply/replies, returns the new messages.

        on_token(text) receives the reply progressively (normal questions only; reviews are built as a whole)."""
        say, on_token = on_status or _noop, on_token or _noop
        conv = repo.get_conversation(conversation_id)
        project = repo.get_project(conv["project_id"])
        user = repo.get_user()
        rule, info = self.language_rule(text, user, conv.get("language", ""))
        if info.name != "unknown" and (len(text.split()) >= 3 or not info.name.startswith("English")):
            repo.set_conversation_language(conversation_id, info.name)   # tiny replies ("ok") never reset the language
        paths = [Path(p) for p in (paths or [])]
        meta = {"attachments": [p.name for p in paths], "mode": "submit" if (mode == "submit" or paths) else "ask"}
        repo.add_message(conversation_id, "user", text or "(files attached)", metadata=meta)
        if meta["mode"] == "submit":
            return self._submission(conversation_id, project, user, text, paths, rule, say)
        return self._question(conversation_id, project, user, text, rule, say, on_token, cancel, info.reply_name)

    # ---- project state helpers --------------------------------------------------------------------------------------
    @staticmethod
    def _roadmap_text(tasks: list[dict]) -> str:
        return "\n".join(f"{t['position']}. [{STATUS_LABEL[t['status']]}] {t['title']}" for t in tasks)

    @staticmethod
    def _block(t: dict, hints: bool = True) -> str:
        sub = "; ".join(t.get("subtasks") or []) or "(none stored - derive 3-5 short steps from the purpose)"
        tools = ", ".join(t.get("tools") or []) or "(choose from TOOLS)"
        lines = [f"Task {t['position']}: {t['title']} [{STATUS_LABEL[t['status']]}]", f"Purpose: {t['description']}",
                 f"Subtasks: {sub}", f"Tools: {tools}", f"Expected output: {t['expected_output']}"]
        if hints and t.get("hints"):
            lines.append("Hints: " + "; ".join(t["hints"]))
        return "\n".join(lines)

    @staticmethod
    def _block_md(t: dict) -> str:
        sub = "\n".join(f"{i}. {s}" for i, s in enumerate(t.get("subtasks") or [], 1))
        parts = [f"## Task {t['position']}: {t['title']}  ({STATUS_LABEL[t['status']]})", t["description"]]
        if sub:
            parts.append("**In this task we will:**\n" + sub)
        if t.get("tools"):
            parts.append("**Tools:** " + ", ".join(t["tools"]))
        parts.append(f"**Expected output:** {t['expected_output']}")
        return "\n\n".join(parts)

    @staticmethod
    def _review_summary(task: dict | None) -> str:
        rep = repo.latest_report(task["id"]) if task else None
        if not rep:
            return ""
        failed = [r["description"] for r in loads(rep["rule_results_json"], []) if r.get("status") == "failed"][:4]
        missing = ((loads(rep["llm_review_json"], None) or {}).get("missing") or [])[:3]
        s = rep["status"]
        if failed:
            s += " - unmet checks: " + "; ".join(failed)
        if missing:
            s += " - reviewer notes: " + "; ".join(missing)
        return s

    def _pending(self, task: dict) -> str:
        if task["attempts"]:
            done = f"{task['attempts']} submission(s) so far; latest result: {self._review_summary(task) or 'n/a'}."
        else:
            done = "nothing has been submitted for it yet."
        return (f"Task {task['position']} ({task['title']}) is NOT validated yet - {done} To get it validated the student "
                f"must use Submit for review (attach files or type the answer). Expected output: {task['expected_output']}")

    @staticmethod
    def _intro_seen(cid: int, task_id: int) -> bool:
        return any((m.get("metadata") or {}).get("intro_task") == task_id for m in repo.list_messages(cid, limit=400))   # whole conversation, not just the recent window

    @staticmethod
    def _links_block(names: list[str], limit: int = 8) -> str:
        """Verified official sources only (curated catalog, clickable titles). '' when nothing is known - never a guess."""
        return resource_manager.links_block(names, limit)

    def _tool_lines(self, tools: list[dict], tasks: list[dict]) -> str:
        out = []
        for t in tools:
            uses = ", ".join(str(x["position"]) for x in resource_manager.tasks_using(t["name"], tasks))
            out.append(f"- {t['name']}: {t['detail'] or 'part of the project plan'}" + (f" (Tasks {uses})" if uses else ""))
        return "\n".join(out)

    # ---- planning a reply from the intent + REAL state --------------------------------------------------------------
    def _plan(self, it: intent_router.Intent, project: dict, tasks: list[dict], tools: list[dict], cid: int) -> Plan:
        active = next((t for t in tasks if t["status"] == "active"), None)
        by_pos = {t["position"]: t for t in tasks}
        n_tasks = len(tasks)
        tool_names = [t["name"] for t in tools]
        kind = it.kind

        def resolve_target(default: dict | None) -> dict | None:
            if it.tasks:
                return by_pos.get(it.tasks[0])
            if it.relative == "previous":
                base = (active["position"] if active else n_tasks + 1) - 1
                return by_pos.get(max(1, base))
            if it.relative == "last":
                return by_pos.get(n_tasks)
            if it.relative == "next" and active:
                return by_pos.get(active["position"] + 1) or active
            return default

        if project["status"] == "completed" or not active:
            active_txt = "The project is COMPLETE: every task is validated."
        else:
            active_txt = f"Current task: {active['position']} - {active['title']}."

        if kind == "explain_roadmap":
            details = "\n\n".join(self._block(t, hints=False) for t in tasks)
            return Plan("Explain the COMPLETE roadmap: for every task give its title, purpose, subtasks, tools and expected "
                        "output in a compact, readable form, mark which tasks are completed/current/locked, and end by saying "
                        "where the student is now. Explaining locked tasks is allowed (they are previews).",
                        details, MAX_TOKENS[kind], self._links_block(tool_names, 6),
                        "\n\n".join(self._block_md(t) for t in tasks) + f"\n\n{active_txt}")

        if kind == "explain_task" or (kind in ("advance", "completion") and it.out_of_range and not it.tasks):
            if it.out_of_range and not it.tasks:
                msg = f"There is no Task {it.out_of_range[0]}: this roadmap has {n_tasks} tasks."
                return Plan(f"{msg} Say so politely and list the {n_tasks} task titles briefly.", self._roadmap_text(tasks),
                            300, "", msg + "\n\n" + self._roadmap_text(tasks))
            target = resolve_target(active or by_pos.get(n_tasks))
            targets = [by_pos[n] for n in it.tasks if n in by_pos] or [target]
            first = targets[0]
            preview = ""
            if first["status"] == "locked" and active:
                preview = (f" It is LOCKED (a preview): in one short sentence say Task {active['position']} must be validated "
                           "first, then explain it fully anyway - the student is allowed to ask about any task.")
            tool_for_links = [x for t in targets for x in (t.get("tools") or [])] or tool_names[:4]
            before = self._links_block(tool_for_links, 5)
            return Plan(f"The student asks about Task {first['position']} ({first['title']}); status {STATUS_LABEL[first['status']]}."
                        " Explain it in simple words: its purpose, the subtasks (3-6 numbered steps; use the listed ones or "
                        "derive them), the tools needed (only from TOOLS), the expected output, and what to understand "
                        "before starting. If they also asked about libraries for this task, answer that directly." + preview +
                        " Do not repeat unrelated parts of the roadmap. No code.",
                        "\n\n".join(self._block(t) for t in targets), MAX_TOKENS[kind] + (300 if len(targets) > 1 else 0),
                        ("\n\n**Before you start, read:**" + before.split("\n", 1)[1]) if before else "",
                        "\n\n".join(self._block_md(t) for t in targets),
                        intro_task=first["id"] if first["status"] == "active" else None)

        if kind in ("advance", "whats_next", "completion", "acknowledge"):
            if not active:
                msg = "Every task is already validated - the project is complete."
                return Plan(msg + " Congratulate the student and offer to review any task.", "(none)", 250, "", msg)
            pending = self._pending(active)
            seen = self._intro_seen(cid, active["id"])
            target = resolve_target(None)

            if kind == "completion":
                t = target or active
                if t["status"] == "passed":
                    return Plan(f"The student says Task {t['position']} is done. It IS validated already (passed). Confirm "
                                f"briefly and point to the current task ({active['position']} - {active['title']}).",
                                self._block(active), MAX_TOKENS[kind], "",
                                f"Task {t['position']} is already validated. {active_txt}")
                msg = (f"I can't see that work yet. {pending}") if t["id"] == active["id"] else \
                    f"Task {t['position']} is locked: finish Task {active['position']} first. {pending}"
                return Plan("The student says a task is complete. You cannot verify claims and must not mark anything done: "
                            f"{pending} Tell them kindly and concretely to submit it for validation (Submit for review) - do not "
                            "congratulate yet, do not move on.", self._block(active), MAX_TOKENS[kind], "", msg)

            if kind == "acknowledge":
                nxt = ("It has not been introduced yet - introduce it briefly." if not seen else
                       "It was already explained - do NOT explain it again.")
                return Plan("The student only acknowledged / said they understood. Do NOT repeat any explanation and do NOT treat "
                            "this as task completion. Reply in 1-3 short sentences: confirm, then give the single next action "
                            f"for Task {active['position']} (do the work, then Submit for review). {nxt}",
                            self._block(active), MAX_TOKENS[kind], "",
                            f"Great. {active_txt} Do the work yourself, then use Submit for review so I can validate it. "
                            "Ask me anything while you work.", intro_task=None if seen else active["id"])

            t = target if it.tasks else None
            if t is not None and t["position"] < active["position"]:
                return Plan(f"The student wants Task {t['position']}, which is ALREADY validated. Say so, offer to explain it "
                            f"again, and point to the current task {active['position']} - {active['title']}.", self._block(active),
                            MAX_TOKENS["whats_next"], "", f"Task {t['position']} is already validated. {active_txt}")
            if t is not None and t["position"] > active["position"]:
                msg = (f"Task {t['position']} ({t['title']}) is locked until Task {active['position']} is validated. {pending} "
                       f"You can still ask me to explain Task {t['position']} as a preview.")
                return Plan(f"The student wants to move to Task {t['position']}, but Task {active['position']} has not been "
                            f"validated. {pending} Do NOT proceed and do NOT mark anything done. Explain kindly what is still "
                            f"required and how to submit it; mention they may ask for a preview of Task {t['position']}. "
                            "No needless questions.", self._block(active), MAX_TOKENS[kind], "", msg)
            explicit_open = t is not None and t["id"] == active["id"]
            if explicit_open or (not seen and active["position"] > 1) or (not seen and kind == "whats_next"):
                nth = f"Great! Let's move to Task {active['position']} - {active['title']}." if active["position"] > 1 \
                    else f"Let's start Task 1 - {active['title']}."
                return Plan(f"The student wants to continue with Task {active['position']} and it is OPEN (all earlier tasks are "
                            f"validated). Start with: \"{nth}\" then \"In this task, we will:\" and a numbered list of the "
                            "subtasks, then \"Expected Output:\" and finish with the first concrete step. Mention tools only "
                            "from TOOLS. No code.", self._block(active), MAX_TOKENS["advance"],
                            self._links_block(active.get("tools") or [], 4), nth + "\n\n" + self._block_md(active),
                            intro_task=active["id"])
            after = by_pos.get(active["position"] + 1)
            follow = f" After it comes Task {after['position']} - {after['title']}." if after else ""
            word = "asks what comes next" if kind == "whats_next" else "wants to move on"
            return Plan(f"The student {word}. {pending}{follow} Do NOT proceed to the next task and do NOT mark anything done. "
                        "Tell them plainly that the next step is to finish and submit THIS task, give the first concrete "
                        "step to take (no code), and mention what follows in one sentence. Do not re-explain the whole task.",
                        self._block(active), MAX_TOKENS["whats_next"], "", f"{pending}{follow}")

        if kind in ("tools", "resources"):
            named = it.tools or tool_names
            lines = self._tool_lines(tools, tasks)
            how = ("Answer from TOOLS and the roadmap: for each tool needed, one line on why it is needed and in which tasks. "
                   "Do NOT list tools this project does not need." if kind == "tools" else
                   "Give a learning order tied to the roadmap: what to learn before each task, in short lines.")
            return Plan(f"The student asks about {'the libraries/tools/technologies' if kind == 'tools' else 'what to learn'} "
                        f"for this project. {how} Do not write any URL (the application adds verified official links). "
                        "Select tools by the project's real needs.", "TOOLS (with roles):\n" + lines,
                        MAX_TOKENS[kind], self._links_block(named, 8), "Tools for this project:\n" + lines)

        # concept / error / followup / ambiguous
        extra = self._links_block(it.tools, 3) if it.tools else ""
        how = {"error": "Follow the 7-step error-explanation approach and relate it to this project. Do not supply corrected code.",
               "concept": "Answer directly in the context of THIS project (its data, tasks and tools). If they ask which "
                          "algorithm/metric/tool to use, recommend 2-3 suitable options and say why for this project.",
               }.get(kind, "Answer in the context of the conversation and this project; if the message is short, treat it as "
                           "a follow-up to the previous turn.")
        return Plan(how, self._block(active) if active else "(none)", MAX_TOKENS.get(kind, 600), extra, "")

    # ---- normal questions -------------------------------------------------------------------------------------------
    def _question(self, cid, project, user, text, rule, say, on_token, cancel=None, lang_name: str = "") -> list[dict]:
        t0 = time.perf_counter()
        pid = project["id"]
        tasks, tools = repo.list_tasks(pid), repo.list_requirements(pid, "tool")
        it = intent_router.classify(text, project, tasks, [t["name"] for t in tools])
        tm = {"intent": it.kind, "route_ms": round((time.perf_counter() - t0) * 1000, 1)}
        meta = {"intent": it.kind}

        if it.project_related is False:                       # genuinely unrelated: no LLM call at all
            reply = prompts.off_topic_reply(lang_name)            # fixed text, in the student's language
            on_token(reply)
            return [repo.add_message(cid, "assistant", reply, metadata={**meta, "timings": tm})]

        plan = self._plan(it, project, tasks, tools, cid)
        active = next((t for t in tasks if t["status"] == "active"), None)
        t1 = time.perf_counter()
        chunks = retriever.retrieve(f"{project['title']} {text}", k=3) if it.needs_rag else []   # global KB only
        tm["retrieve_ms"] = round((time.perf_counter() - t1) * 1000, 1)
        state = (f"Task {active['position']} '{active['title']}' - open, attempts {active['attempts']}" if active
                 else "none - project completed")
        system = prompts.system_prompt(
            f"{user['name']} (skill level: {user['skill_level']})",
            f"{project['title']} - {project['objective']} (language: {project['programming_language']}, {project['status']})",
            state, self._review_summary(active), retriever.format_chunks(chunks, 1500), rule,
            roadmap=self._roadmap_text(tasks), details=plan.details, tools=", ".join(t["name"] for t in tools),
            allow_off_topic=it.project_related is None)
        history = build_history(cid)
        if not history or history[-1]["role"] != "user":
            history.append({"role": "user", "content": text})
        history[-1] = {"role": "user", "content": history[-1]["content"] +
                       "\n\n[MENTOR NOTE - written by the application, not by the student]\n" + plan.directive}
        msgs = [{"role": "system", "content": system}] + history
        tm["prompt_chars"] = sum(len(m["content"]) for m in msgs)
        say("Thinking...")
        try:
            cap = int(settings.get("CHAT_MAX_TOKENS") or 900)      # shorter ceiling = faster answers (roadmap overview exempt)
            limit = plan.max_tokens if it.kind == "explain_roadmap" else min(plan.max_tokens, cap)
            final, violations, off, stats = self._stream(msgs, limit, on_token,
                                                         allow_off_topic=it.project_related is None, cancel=cancel)
            if not final:
                raise LLMError("The model returned an empty answer.")
            if off:
                meta["intent"] = "unrelated"
                final = prompts.off_topic_reply(lang_name)
            elif plan.append:
                on_token(plan.append)
                final += plan.append
            if plan.intro_task and not off:
                meta["intro_task"] = plan.intro_task
            tm.update(self._timing(stats, t0))
            log.info("chat timings: %s", self._fmt_stats(tm))
            return [repo.add_message(cid, "assistant", final, metadata={**meta, "guard_violations": violations,
                                                                         "timings": tm})]
        except LLMError as exc:
            if plan.fallback:                                    # workflow answers still work without the model
                text_out = OFFLINE_PREFIX + plan.fallback + plan.append
                on_token(text_out)
                if plan.intro_task:
                    meta["intro_task"] = plan.intro_task
                return [repo.add_message(cid, "assistant", text_out, metadata={**meta, "offline": True, "timings": tm})]
            return [repo.add_message(cid, "system", UNAVAILABLE_HELP.format(err=exc), kind="notice")]

    @staticmethod
    def _timing(stats: dict, t0: float) -> dict:
        out = {"total_s": round(time.perf_counter() - t0, 2)}
        if stats.get("ttft_s") is not None:
            out["first_token_s"] = round(stats["ttft_s"], 2)
        for key, name in (("load_duration", "model_load_s"), ("prompt_eval_duration", "prompt_eval_s"),
                          ("eval_duration", "generation_s")):
            if stats.get(key):
                out[name] = round(stats[key] / 1e9, 2)
        for key in ("prompt_eval_count", "eval_count"):
            if stats.get(key):
                out[key] = stats[key]
        if out.get("eval_count") and out.get("generation_s"):
            out["tokens_per_s"] = round(out["eval_count"] / out["generation_s"], 1)
        return out

    @staticmethod
    def _fmt_stats(d: dict) -> str:
        return ", ".join(f"{k}={v}" for k, v in d.items())

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
            nt = outcome.next_task
            out.append(repo.add_message(cid, "assistant", self._after_pass(project, outcome, rule),
                                        metadata={"intro_task": nt["id"]} if nt else {}))
        return out

    def _after_pass(self, project: dict, outcome, rule: str) -> str:
        tasks = repo.list_tasks(project["id"])
        try:
            if outcome.project_done:
                return self._llm_text(
                    prompts.system_prompt("student", project["title"], "none - project complete", "", "", rule,
                                          allow_off_topic=False),
                    prompts.COMPLETION_PROMPT.format(title=project["title"], language_rule=rule,
                                                     stages=task_manager.roadmap_summary(tasks)))
            nt = outcome.next_task
            return self._llm_text(
                prompts.system_prompt("student", project["title"], task_manager.describe_task(nt), "", "", rule,
                                          roadmap=self._roadmap_text(tasks), allow_off_topic=False),
                prompts.NEXT_TASK_PROMPT.format(language_rule=rule, n=nt["position"], title=nt["title"],
                                                desc=nt["description"], out=nt["expected_output"],
                                                hints="; ".join(nt["hints"]) or "none"))
        except LLMError:
            if outcome.project_done:
                return f"Congratulations - **{project['title']}** is complete and fully validated!"
            nt = outcome.next_task
            return (f"## Task {nt['position']}: {nt['title']}\n{nt['description']}\n\n"
                    f"**Expected output:** {nt['expected_output']}\n\nSubmit it when ready.")
