"""Conversation understanding / task progression tests for the 'Student Performance Predictor' project.

The LLM is replaced by a recording fake, so these tests prove what the application DECIDES (intent, workflow state,
what context and instructions the model receives, what is appended, what is never changed) - not how well a real
model words its answer. Run: python -m pytest -q tests/test_conversation.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["MENTOR_STORAGE_DIR"] = tempfile.mkdtemp(prefix="mentor_conv_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from ai_engine import intent_router, llm_provider, prompts  # noqa: E402
from ai_engine.assistant import Mentor, sanitize_urls  # noqa: E402
from ai_engine.language_detector import detect  # noqa: E402
from ai_engine.llm_provider import LLMProvider, LLMUnavailable  # noqa: E402
from database import db, repository as repo  # noqa: E402
from learning import resource_manager  # noqa: E402
from project_manager import roadmap_generator  # noqa: E402

TITLES = ["Project Understanding and Planning", "Importing Libraries and Loading Data", "Data Preprocessing",
          "Feature Scaling", "Model Training", "Model Evaluation", "Model Deployment"]
TOOLS = [("Python", "main language"), ("Pandas", "data loading and manipulation"), ("NumPy", "numerical operations"),
         ("Matplotlib", "data visualization"), ("Seaborn", "statistical visualization"),
         ("Scikit-learn", "preprocessing, model training and evaluation")]
STAGE_TOOLS = {2: ["Pandas", "NumPy"], 3: ["Pandas"], 4: ["Scikit-learn"], 5: ["Scikit-learn"], 6: ["Scikit-learn", "Matplotlib"]}


class Recorder(LLMProvider):
    """Fake model: records every request; semantic reviews answer 'pass'; everything else returns a short sentence."""
    name = "recorder"

    def __init__(self):
        self.model, self.base_url, self.api_key, self.timeout, self.temperature = "fake", "", "", 5, 0.1
        self.last_stats: dict = {}
        self.calls: list[list[dict]] = []
        self.reply = "Sure - here is the explanation."
        self.pieces: list[str] | None = None
        self.down = False

    def chat(self, messages, temperature=None, max_tokens=4096, json_mode=False):
        if self.down:
            raise LLMUnavailable("server down")
        last = messages[-1]["content"]
        if "semantic reviewer" in last:
            return json.dumps({"verdict": "pass", "implemented_correctly": ["covers the plan"], "missing": [],
                               "observations": [], "suggestions": [], "mentor_message": "Good."})
        self.calls.append(messages)
        return self.reply

    def stream_chat(self, messages, temperature=None, max_tokens=4096, cancel=None):
        if self.down:
            raise LLMUnavailable("server down")
        if self.pieces is not None:
            self.calls.append(messages)
            yield from self.pieces
        else:
            yield self.chat(messages, temperature, max_tokens)


@pytest.fixture(scope="module")
def env():
    db.init_db()
    fake = Recorder()
    llm_provider.set_provider_override(fake)
    yield Mentor(), fake
    llm_provider.set_provider_override(None)


def make_project(title="Student Performance Predictor"):
    stages = []
    for i, name in enumerate(TITLES, 1):
        t = i == 1
        stages.append({"title": name, "description": f"Purpose of {name}.", "expected_output": f"Output of {name}.",
                       "deliverable_type": "text" if t else "code", "hints": ["a hint"],
                       "subtasks": [f"{name} step A", f"{name} step B"], "tools": STAGE_TOOLS.get(i, ["Python"]),
                       "checks": ([{"type": "text_mentions", "description": "mentions objective, attendance and grades",
                                    "params": {"groups": [["objective", "goal"], ["attendance"], ["grades", "marks"]]}}]
                                  if t else [])})
    tasks = [roadmap_generator.normalize_stage(s) for s in stages] + [roadmap_generator.final_task("Python")]
    user = repo.get_user()
    pid = repo.create_project(user["id"], title, "Student Performance Predictor idea",
                              "Predict student performance based on historical attendance and grades.", "Data Science",
                              "Python", "beginner", "llm", [{"name": n, "role": r} for n, r in TOOLS], ["predict grades"], tasks)
    cid = repo.create_conversation(user["id"], pid, title)
    repo.add_message(cid, "user", "I want to build a Student Performance Predictor")
    t1 = repo.list_tasks(pid)[0]
    repo.add_message(cid, "assistant", "Welcome! Task 1: Project Understanding and Planning ...",
                     metadata={"intro_task": t1["id"], "intent": "intro"})
    return pid, cid


def statuses(pid):
    return [t["status"] for t in repo.list_tasks(pid)]


def ask(env_, cid, text):
    mentor, fake = env_
    before = len(fake.calls)
    out = mentor.chat(cid, text)
    sent = fake.calls[-1] if len(fake.calls) > before else None
    return out[0], sent


def note(sent):
    return sent[-1]["content"].split("[MENTOR NOTE")[1]


# ------------------------------------------------------------------------------------------------ the 11 required messages
def test_libraries_question_is_answered_not_rejected(env):
    pid, cid = make_project()
    for msg in ("Libraries ennalam venum?", "Which libraries should I install?"):
        reply, sent = ask(env, cid, msg)
        assert sent is not None, "the LLM must be called"
        assert reply["content"] != prompts.OFF_TOPIC_REPLY and reply["metadata"]["intent"] == "tools"
        system = sent[0]["content"]
        assert prompts.OFF_TOPIC_TOKEN not in system and "HAS BEEN CHECKED" in system   # the model cannot refuse it
        assert "Pandas: data loading" in system and "Scikit-learn: preprocessing" in system and "Django" not in system
        assert "https://pandas.pydata.org/docs/" in reply["content"]                # verified official links appended
        assert "scikit-learn.org" in reply["content"]


def test_explain_task_2_even_though_task_1_is_open(env):
    pid, cid = make_project()
    reply, sent = ask(env, cid, "Task 2 explain pannunga")
    assert reply["metadata"]["intent"] == "explain_task"
    assert "Task 2: Importing Libraries and Loading Data [Locked]" in sent[0]["content"]
    assert "preview" in note(sent) and "Task 1" in note(sent)
    assert "Before you start, read" in reply["content"] and "pandas.pydata.org" in reply["content"]
    assert statuses(pid)[:2] == ["active", "locked"]


def test_move_to_task_2_with_task_1_unvalidated_is_blocked_but_explained(env):
    pid, cid = make_project()
    before = statuses(pid)
    reply, sent = ask(env, cid, "Task 2 ku move pannalam")
    assert reply["metadata"]["intent"] == "advance" and reply["content"] != prompts.OFF_TOPIC_REPLY
    n = note(sent)
    assert "NOT validated" in n and "Do NOT proceed" in n and "Submit for review" in n
    assert statuses(pid) == before                                                  # nothing moved


def test_next_enna_uses_real_state(env):
    pid, cid = make_project()
    reply, sent = ask(env, cid, "Next enna?")
    assert reply["metadata"]["intent"] == "whats_next"
    assert "NOT validated" in note(sent) and "After it comes Task 2 - Importing Libraries and Loading Data" in note(sent)


def test_explain_any_task_and_whole_roadmap(env):
    pid, cid = make_project()
    reply, sent = ask(env, cid, "Task 3 la enna irukku?")
    assert reply["metadata"]["intent"] == "explain_task" and "Task 3: Data Preprocessing" in sent[0]["content"]
    reply, sent = ask(env, cid, "Ella tasks um explain pannu")
    assert reply["metadata"]["intent"] == "explain_roadmap"
    for t in TITLES + ["Final Validation and Project Completion"]:
        assert t in sent[0]["content"]
    reply, sent = ask(env, cid, "What libraries do we need for Task 5?")
    assert "Task 5: Model Training" in sent[0]["content"] and "scikit-learn.org" in reply["content"]
    reply, sent = ask(env, cid, "Explain task 12")
    assert "no Task 12" in note(sent) or "There is no Task 12" in note(sent)


@pytest.mark.parametrize("msg,expect", [
    ("Why Pandas?", "concept"), ("What algorithm should I use?", "concept"), ("Feature scaling ethuku?", "concept"),
    ("Model evaluation eppadi pannuvom?", "concept"), ("Why are we using Random Forest?", "concept"),
    ("Which performance metrics should I use?", "concept"), ("What is the purpose of NumPy?", "concept"),
    ("What should I learn before model training?", "resources"), ("ModuleNotFoundError: No module named pandas", "error"),
])
def test_technical_questions_are_project_related(env, msg, expect):
    pid, cid = make_project()
    reply, sent = ask(env, cid, msg)
    assert sent is not None and reply["metadata"]["intent"] == expect
    assert prompts.OFF_TOPIC_TOKEN not in sent[0]["content"]
    assert "Student Performance Predictor" in sent[0]["content"]                     # answered in project context


def test_pandas_question_appends_its_official_links(env):
    pid, cid = make_project()
    reply, _ = ask(env, cid, "Why Pandas?")
    assert "https://pandas.pydata.org/docs/user_guide/10min.html" in reply["content"] or "pandas.pydata.org" in reply["content"]
    assert "scikit-learn.org" not in reply["content"]                                # only the tool asked about


# ------------------------------------------------------------------------------------------------ progression rules
def test_acknowledgement_and_completion_claim_do_not_change_state(env):
    pid, cid = make_project()
    before = statuses(pid)
    reply, sent = ask(env, cid, "Okay, I understand.")
    assert reply["metadata"]["intent"] == "acknowledge" and "do NOT repeat" in note(sent).replace("Do NOT", "do NOT")
    reply, sent = ask(env, cid, "I have completed Task 1.")
    assert reply["metadata"]["intent"] == "completion" and "cannot verify" in note(sent)
    reply, sent = ask(env, cid, "Task 1 complete. What next?")
    assert reply["metadata"]["intent"] == "completion"
    assert statuses(pid) == before and repo.get_progress(pid)["completed_tasks"] == 0


def test_after_validation_moving_on_explains_task_2(env):
    mentor, fake = env
    pid, cid = make_project()
    answer = ("The objective is to predict student performance from historical attendance and grades. The plan is to load "
              "the dataset, clean it, scale features, train a model and evaluate it using suitable metrics for grades.")
    out = mentor.chat(cid, answer, mode="submit")
    assert out[0]["metadata"]["status"] == "Passed"
    assert statuses(pid)[:3] == ["passed", "active", "locked"]
    assert out[1]["metadata"]["intro_task"] == repo.get_active_task(pid)["id"]       # task 2 was introduced automatically
    reply, sent = ask(env, cid, "Task 2 ku move pannalam")                           # explicit: kick-off Task 2
    n = note(sent)
    assert "Great! Let's move to Task 2 - Importing Libraries and Loading Data." in n and "In this task, we will:" in n
    assert "Expected Output:" in n
    reply, sent = ask(env, cid, "Next task polam")                                    # implicit: Task 2 was already introduced
    assert "NOT validated" in note(sent) and "Task 2" in note(sent)
    assert statuses(pid)[:3] == ["passed", "active", "locked"]                       # saying 'next' never advances
    reply, sent = ask(env, cid, "Task 4 ku polam")                                    # skipping ahead is blocked
    assert "Do NOT proceed" in note(sent) and statuses(pid)[3] == "locked"


# ------------------------------------------------------------------------------------------------ scope
@pytest.mark.parametrize("msg", ["What is the weather today?", "Who won the IPL match yesterday?", "Tell me a joke",
                                 "enaku biryani recipe sollu", "give me the capital of France please and explain it"])
def test_unrelated_questions_get_the_fixed_reply_without_calling_the_llm(env, msg):
    pid, cid = make_project()
    reply, sent = ask(env, cid, msg)
    expected = prompts.off_topic_reply(detect(msg).reply_name)          # same fixed text, in the student's language
    assert reply["content"] == expected and sent is None


def test_unsure_messages_let_the_llm_decide_but_never_force_a_refusal(env):
    mentor, fake = env
    pid, cid = make_project()
    long_odd = "my neighbour keeps asking about something I do not really follow and it is confusing me a lot today"
    assert intent_router.classify(long_odd).project_related is None
    fake.reply = prompts.OFF_TOPIC_TOKEN
    reply, sent = ask(env, cid, long_odd)
    fake.reply = "Sure - here is the explanation."
    assert prompts.OFF_TOPIC_TOKEN in sent[0]["content"] and reply["content"] == prompts.OFF_TOPIC_REPLY


# ------------------------------------------------------------------------------------------------ language, safety, streaming
def test_language_is_detected_per_message_and_explicit_requests_win(env):
    assert detect("Libraries ennalam venum?").name == "Tanglish"
    assert detect("Task 2 ku move pannalam").name == "Tanglish"
    assert detect("Feature scaling ethuku?").name == "Tanglish"
    assert detect("Can you explain this error in Tamil?").requested == "Tamil"
    pid, cid = make_project()
    _, sent = ask(env, cid, "Can you explain this error in Tamil? ModuleNotFoundError: No module named pandas")
    assert "explicitly asked for Tamil" in sent[0]["content"]
    _, sent = ask(env, cid, "Why Pandas?")
    assert "explicitly asked" not in sent[0]["content"]                              # per message, not a setting


def test_llm_cannot_inject_unverified_links(env):
    mentor, fake = env
    pid, cid = make_project()
    fake.reply = "Read https://totally-fake.example/pandas and https://pandas.pydata.org/docs/ please."
    reply, _ = ask(env, cid, "Why Pandas?")
    fake.reply = "Sure - here is the explanation."
    assert "totally-fake" not in reply["content"] and "[unverified link removed]" in reply["content"]
    assert "https://pandas.pydata.org/docs/" in reply["content"]
    assert "x" not in sanitize_urls("no links here").replace("no links here", "")
    allowed = resource_manager.find_doc("Pandas")
    assert sanitize_urls(f"see {allowed}.") == f"see {allowed}."


def test_streaming_shows_text_progressively_and_never_shows_code(env):
    mentor, fake = env
    pid, cid = make_project()
    fake.pieces = ["Think about ", "it like this:\n", "```pyth", "on\ndef solve(df):\n", "    return df\n```\n", "Then try it yourself."]
    seen: list[str] = []
    out = mentor.chat(cid, "Why Pandas?", on_token=seen.append)
    fake.pieces = None
    streamed = "".join(seen)
    assert len(seen) > 2 and streamed.startswith("Think")                           # arrived in pieces
    assert "def solve" not in streamed and "def solve" not in out[0]["content"]
    assert "code removed" in out[0]["content"].lower() and "Then try it yourself." in out[0]["content"]
    assert "total_s" in out[0]["metadata"]["timings"]                                 # timing recorded for every answer


def test_workflow_questions_still_work_when_the_llm_is_down(env):
    mentor, fake = env
    pid, cid = make_project()
    fake.down = True
    try:
        reply, _ = ask(env, cid, "Ella tasks um explain pannu")
        assert reply["metadata"].get("offline") and "Task 7: Model Deployment" in reply["content"]
        reply, _ = ask(env, cid, "Task 2 ku move pannalam")
        assert "NOT validated" in reply["content"]
        reply, _ = ask(env, cid, "Libraries ennalam venum?")
        assert "pandas.pydata.org" in reply["content"]
        reply, _ = ask(env, cid, "Why are we using Random Forest?")                  # needs the model -> honest notice
        assert reply["kind"] == "notice"
    finally:
        fake.down = False


def test_task_introduced_long_ago_is_not_re_explained(env):
    pid, cid = make_project()
    for i in range(20):                                   # a long conversation pushes the introduction out of any window
        ask(env, cid, "Why Pandas?")
    reply, sent = ask(env, cid, "Next enna?")
    assert "NOT validated" in note(sent) and "Let's start Task 1" not in note(sent)


def test_chat_max_tokens_setting_is_applied(env):
    from config import settings
    mentor, fake = env
    seen = []
    orig = fake.stream_chat
    fake.stream_chat = lambda messages, temperature=None, max_tokens=4096, cancel=None: (seen.append(max_tokens), orig(messages))[1]
    pid, cid = make_project()
    try:
        settings.update({"CHAT_MAX_TOKENS": "300"})
        ask(env, cid, "Why Pandas?")
        ask(env, cid, "Ella tasks um explain pannu")
    finally:
        settings.update({"CHAT_MAX_TOKENS": "900"})
        fake.stream_chat = orig
    assert seen[0] == 300 and seen[1] == 1500            # normal answers capped; the full roadmap overview is exempt
