"""Backward compatibility with the PREVIOUS release.

tests/fixtures/legacy_v2.db was created by the previous version's own code (a project with 8 tasks, a conversation with
Tanglish questions, a passed submission, learning notes) and legacy_settings.json is an old-style settings file (single
LLM_API_KEY, LLM_MODEL...). The new code must read, continue and not damage them.
"""
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

FIX = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

import config  # noqa: E402
from ai_engine import llm_provider as lp, prompts  # noqa: E402
from ai_engine.assistant import Mentor  # noqa: E402
from config import settings  # noqa: E402
from database import db, models, repository as repo  # noqa: E402
from utils import secrets  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def legacy_storage():
    """Point the (process-wide) configuration at a copy of the legacy files for THIS module only, then restore it."""
    store = Path(tempfile.mkdtemp(prefix="mentor_compat_"))
    shutil.copy(FIX / "legacy_v2.db", store / "mentor.db")
    shutil.copy(FIX / "legacy_settings.json", store / "settings.json")
    mp = pytest.MonkeyPatch()
    for mod, name, value in ((config, "STORAGE_DIR", store), (config, "DB_PATH", store / "mentor.db"),
                             (config, "SETTINGS_PATH", store / "settings.json"), (db, "DB_PATH", store / "mentor.db"),
                             (db, "STORAGE_DIR", store)):
        mp.setattr(mod, name, value)
    saved = dict(settings._overrides)
    settings.reload()
    secrets.reset_probe()
    secrets._KEYRING = False
    lp._cached = None
    yield store
    mp.undo()
    settings._overrides.clear()
    settings._overrides.update(saved)
    secrets.reset_probe()
    secrets._KEYRING = False
    lp._cached = None


PREVIOUS_SCHEMA_SHA256 = "323bc18b0fdc8004724d57c502e3dec8ea92f4503e269d8d4738f4af2379c250"


def test_database_schema_is_unchanged():
    assert hashlib.sha256(models.SCHEMA.encode()).hexdigest() == PREVIOUS_SCHEMA_SHA256       # no migration needed


@pytest.fixture(scope="module")
def legacy(legacy_storage):
    db.init_db()                                              # must open the old file without touching its data
    user = repo.get_user()
    return user, repo.list_projects(user["id"])[0]


def test_old_projects_conversations_and_history_are_intact(legacy):
    user, project = legacy
    assert project["title"] == "Legacy Student Performance Predictor"
    tasks = repo.list_tasks(project["id"])
    assert [t["status"] for t in tasks][:3] == ["passed", "active", "locked"] and len(tasks) == 8
    assert repo.get_progress(project["id"])["completed_tasks"] == 1
    conv = repo.get_conversation_for_project(project["id"])
    msgs = repo.list_messages(conv["id"])
    assert len(msgs) == 9 and any(m["content"] == "Libraries ennalam venum?" for m in msgs)
    assert repo.list_notes(project["id"])                                           # learning notes survive
    assert repo.list_submissions(tasks[0]["id"]) and repo.latest_report(tasks[0]["id"])["status"] == "Passed"


def test_old_task_format_still_works(legacy):
    _u, project = legacy
    t = repo.list_tasks(project["id"])[1]
    assert isinstance(t["hints"], list) and isinstance(t["checks"], list)             # tolerant of the stored hint formats


def test_old_settings_file_keeps_working_and_the_key_is_not_lost():
    assert settings.get("THEME") == "light" and settings.active_provider == "anthropic"
    assert settings.model_for("anthropic") == "claude-sonnet-5-5"
    p = lp.get_provider()
    assert isinstance(p, lp.AnthropicProvider) and p.api_key == "legacy-plaintext-key-0000"   # single legacy key -> active provider
    assert secrets.get_key("openai") == ""                                                      # ...and only that provider
    assert p.health() == (True, "Anthropic: claude-sonnet-5-5")


def test_legacy_key_migrates_to_the_secure_store_when_one_exists(legacy_storage):
    class KR:
        store: dict = {}
        get_password = classmethod(lambda c, s, u: c.store.get((s, u)))
        set_password = classmethod(lambda c, s, u, v: c.store.__setitem__((s, u), v))
        delete_password = classmethod(lambda c, s, u: c.store.pop((s, u), None))
        get_keyring = classmethod(lambda c: c())
    secrets.reset_probe()
    secrets._KEYRING = KR
    assert secrets.migrate_legacy() is True
    assert KR.store[("ai-project-mentor", "anthropic_api_key")] == "legacy-plaintext-key-0000"
    assert "LLM_API_KEY" not in settings._overrides                                           # plain-text copy removed
    assert "legacy-plaintext" not in (legacy_storage / "settings.json").read_text()
    assert lp.get_provider().api_key == "legacy-plaintext-key-0000"                           # still works for the app
    secrets.reset_probe()
    secrets._KEYRING = False


def test_explicitly_selected_ollama_is_still_supported(monkeypatch):
    settings.update({"LLM_PROVIDER": "ollama", "LLM_MODEL": "llama3.2:3b"})
    lp._cached = None
    assert isinstance(lp.get_provider(), lp.OllamaProvider) and lp.get_provider().model == "llama3.2:3b"
    settings.update({"LLM_PROVIDER": "anthropic", "LLM_MODEL": "claude-sonnet-5-5"})
    lp._cached = None


def test_old_conversation_can_be_continued_with_the_new_mentor(legacy):
    import test_conversation as tc
    _u, project = legacy
    fake = tc.Recorder()
    lp.set_provider_override(fake)
    try:
        m = Mentor()
        cid = m.resume_project(project["id"])                                       # existing conversation is reopened
        assert cid == repo.get_conversation_for_project(project["id"])["id"]
        before = len(repo.list_messages(cid))
        reply = m.chat(cid, "Task 3 la enna irukku?")[0]
        assert reply["metadata"]["intent"] == "explain_task" and fake.calls
        reply = m.chat(cid, "Next enna?")[0]
        assert "NOT validated" in fake.calls[-1][-1]["content"]                       # state read from the OLD database rows
        assert len(repo.list_messages(cid)) == before + 4
        assert m.chat(cid, "what is the weather today")[0]["content"] == prompts.off_topic_reply("English or another Latin-script language")
        assert [t["status"] for t in repo.list_tasks(project["id"])][:3] == ["passed", "active", "locked"]
    finally:
        lp.set_provider_override(None)
