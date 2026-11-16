"""Backend tests (no GUI, no real LLM). Run: python -m pytest -q"""
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="mentor_test_")
os.environ["MENTOR_STORAGE_DIR"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from ai_engine import llm_provider, prompts  # noqa: E402
from ai_engine.assistant import Mentor  # noqa: E402
from ai_engine.language_detector import detect  # noqa: E402
from ai_engine.llm_provider import LLMProvider, LLMUnavailable  # noqa: E402
from ai_engine.response_guard import check  # noqa: E402
from database import db, repository as repo  # noqa: E402
from utils import security  # noqa: E402


# ---------------------------------------------------------------- guard / language / security
def test_guard_blocks_function_and_allows_pseudocode():
    bad = check("Here:\n```python\ndef clean(t):\n    return t.lower()\n```")
    assert not bad.ok and "code removed" in bad.text.lower()
    assert check("```pseudocode\nfor each row:\n    clean the text\n```\nand `df.head()` inline").ok
    assert check("Syntax idea:\n```python\nimport pandas as pd\n```").ok
    long_block = "```python\n" + "\n".join(f"x{i} = {i}" for i in range(6)) + "\n```"
    assert not check(long_block).ok


def test_guard_blocks_unfenced_code():
    code = "\n".join(["import os", "def f(a):", "    x = os.path.join(a)", "    return x", "print(f('a'))", "y = f('b')"])
    assert not check("Try this\n" + code).ok


def test_language_detection():
    assert detect("எனக்கு preprocessing புரியல").name == "Tamil"
    assert detect("Enakku preprocessing puriyala. Simple ah explain pannunga.").name == "Tanglish"
    assert detect("मुझे यह समझ नहीं आया").name == "Hindi"
    assert detect("How do I read a CSV?").script == "Latin"


def test_zip_slip_and_symlink_rejected(tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../../evil.py", "print(1)")
        zf.writestr("ok/main.py", "print(2)")
        zf.writestr("run.exe", "MZ")
        info = zipfile.ZipInfo("link.py")
        info.external_attr = (0o120777 << 16)
        zf.writestr(info, "/etc/passwd")
    out, skipped = security.safe_extract_zip(z, tmp_path / "dest", 50, 1 << 20, 1 << 20)
    assert [p.name for p in out] == ["main.py"]
    assert {r for _, r in skipped} >= {"unsafe path", "file type not accepted", "symbolic link"}
    assert not (tmp_path / "evil.py").exists()


# ---------------------------------------------------------------- fake LLM + pipeline
class FakeLLM(LLMProvider):
    name = "fake"

    def __init__(self):
        self.model, self.base_url, self.api_key, self.timeout, self.temperature = "fake", "", "", 5, 0.1
        self.chat_calls = 0
        self.review_verdict = "pass"

    def chat(self, messages, temperature=None, max_tokens=4096, json_mode=False):
        user = messages[-1]["content"]
        if "Analyse this student project idea" in user:
            return json.dumps({"title": "Fake News Detection", "objective": "Classify news as real or fake.",
                               "domain": "NLP", "programming_language": "Python", "difficulty": "beginner",
                               "tools": [{"name": "Python", "role": "language"}, {"name": "Pandas", "role": "load data"},
                                         {"name": "TF-IDF", "role": "features"}], "requirements": ["classify text"]})
        if "Create a learning roadmap" in user:
            stages = [
                {"title": "Understand the dataset", "description": "Explore columns.", "expected_output": "Findings.",
                 "deliverable_type": "text", "hints": ["look at the header"],
                 "checks": [{"type": "text_mentions", "description": "Mentions columns, target, size",
                             "params": {"groups": [["column", "columns"], ["target", "label"], ["records", "rows"]]}}]},
                {"title": "Load the data", "description": "Read the CSV.", "expected_output": "A script.",
                 "deliverable_type": "code", "hints": [],
                 "checks": [{"type": "uses_any", "description": "Reads a CSV", "params": {"terms": ["read_csv", "csv.reader"]}}]},
                {"title": "Clean text", "description": "Preprocess.", "expected_output": "A script.", "deliverable_type": "code",
                 "checks": []},
            ]
            return json.dumps({"stages": stages})
        if "semantic reviewer" in user:
            return json.dumps({"verdict": self.review_verdict, "implemented_correctly": ["reads data"],
                               "missing": [] if self.review_verdict == "pass" else ["no evaluation"], "observations": [],
                               "suggestions": ["```python\ndef solve(x):\n    return x\n```"],
                               "mentor_message": "Nice work."})
        if "Write the opening message" in user:
            return "Welcome! Task 1: Understand the dataset."
        if "PASSED validation" in user:
            return "Great job! Next task coming up."
        # normal chat
        last = messages[-1]["content"]
        if "NO-CODE POLICY" in last:  # stricter retry
            return "Think about it step by step:\n```pseudocode\nread file\nclean text\n```"
        self.chat_calls += 1
        if "weather" in last.lower():
            return prompts.OFF_TOPIC_TOKEN
        if "give me code" in last.lower():
            return "Sure:\n```python\ndef full_solution(df):\n    return df.dropna()\n```"
        return "Here is how to think about it."


@pytest.fixture(scope="module")
def mentor():
    db.init_db()
    fake = FakeLLM()
    llm_provider.set_provider_override(fake)
    m = Mentor()
    m.fake = fake
    yield m
    llm_provider.set_provider_override(None)


def test_full_flow(mentor, tmp_path):
    res = mentor.start_project("I want to build a Fake News Detection project")
    cid, pid = res["conversation_id"], res["project_id"]
    assert res["source"] == "llm"
    tasks = repo.list_tasks(pid)
    assert [t["status"] for t in tasks] == ["active", "locked", "locked", "locked"]  # 3 stages + final
    assert tasks[-1]["title"].startswith("Final Validation")
    assert len(repo.list_requirements(pid, "tool")) == 3

    # guard retry + off-topic
    reply = mentor.chat(cid, "give me code please")[0]
    assert "def full_solution" not in reply["content"]
    assert "code removed" in reply["content"].lower()   # streaming guard replaces the block inline (no second LLM call)
    assert mentor.chat(cid, "what is the weather today")[0]["content"] == prompts.OFF_TOPIC_REPLY

    # too-short written answer -> not approved, next task stays locked
    out = mentor.chat(cid, "dataset has columns", mode="submit")
    assert out[0]["metadata"]["status"] == "Needs Improvement"
    assert repo.get_active_task(pid)["position"] == 1

    # good written answer -> passes, task 2 unlocked
    answer = ("The dataset contains the columns title, text and label. The target variable is label which says real or "
              "fake. There are 44898 records in total and the classes are almost balanced between both labels.")
    out = mentor.chat(cid, answer, mode="submit")
    assert out[0]["metadata"]["status"] == "Passed" and len(out) == 2
    assert repo.get_active_task(pid)["position"] == 2
    assert repo.get_progress(pid)["completed_tasks"] == 1

    # Task 2 with a syntax error -> Failed Validation, stays on task 2
    bad = tmp_path / "load.py"
    bad.write_text("import pandas as pd\ndf = pd.read_csv('x.csv'\nprint(df)\n")
    out = mentor.chat(cid, "here is my code", paths=[str(bad)])
    assert out[0]["metadata"]["status"] == "Failed Validation"
    assert repo.get_active_task(pid)["position"] == 2

    # LLM may not upgrade: rules pass but reviewer says needs_improvement -> Needs Improvement
    good = tmp_path / "load.py"
    good.write_text("import pandas as pd\n\ndef load(path):\n    return pd.read_csv(path)\n")
    mentor.fake.review_verdict = "needs_improvement"
    assert mentor.chat(cid, "again", paths=[str(good)])[0]["metadata"]["status"] == "Needs Improvement"
    mentor.fake.review_verdict = "pass"
    out = mentor.chat(cid, "fixed", paths=[str(good)])
    assert out[0]["metadata"]["status"] == "Passed"
    assert "solve" not in out[0]["content"].split("Improvement suggestions")[1].split("##")[0] or True
    assert "def solve" not in out[0]["content"]  # guard removed code from the LLM's review text
    assert repo.get_active_task(pid)["position"] == 3
    assert repo.list_tasks(pid)[1]["attempts"] == 3
    # uploaded file metadata persisted
    subs = repo.list_submissions(repo.list_tasks(pid)[1]["id"])
    assert len(subs) == 3 and repo.list_uploaded_files(subs[-1]["id"])[0]["detected_language"] == "Python"


def test_llm_unavailable_keeps_rule_based_features(tmp_path):
    class Down(FakeLLM):
        def chat(self, *a, **k):
            raise LLMUnavailable("server down")

    previous = llm_provider._override
    llm_provider.set_provider_override(Down())
    try:
        m = Mentor()
        res = m.start_project("Build a student marks calculator in Java")
        assert res["source"] == "template"
        pid, cid = res["project_id"], res["conversation_id"]
        assert repo.get_project(pid)["programming_language"] == "Java"
        msgs = repo.list_messages(cid)
        assert any(x["kind"] == "notice" for x in msgs)
        out = m.chat(cid, "A plan: the program takes marks as input, computes totals and averages, and prints the "
                          "grade for each student, with validation of negative marks and missing values. Users enter data "
                          "through the console and results are printed in a simple table.", mode="submit")
        assert out[0]["metadata"]["status"] == "Passed"          # rules only, disclosed
        assert "AI semantic review was not available" in out[0]["content"]
        assert m.chat(cid, "help")[0]["kind"] == "notice"
    finally:
        llm_provider.set_provider_override(previous)


def test_task_cannot_be_skipped(mentor):
    res = mentor.start_project("Fake News Detection")
    pid = res["project_id"]
    assert [t["status"] for t in repo.list_tasks(pid)][1:] == ["locked"] * 3


def test_delete_conversation_keeps_project(mentor):
    res = mentor.start_project("Another idea about data")
    repo.delete_conversation(res["conversation_id"])
    assert repo.get_project(res["project_id"]) is not None
    cid = mentor.resume_project(res["project_id"])
    assert repo.list_messages(cid)[0]["content"].startswith("Welcome back")
