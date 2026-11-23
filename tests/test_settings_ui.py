"""The real Settings screen + App wired to fake cloud APIs (needs a display: run under xvfb-run on Linux; skipped otherwise).

Covers: provider and model selection, key entry/storage, connection validation and status display, testing with unsaved
values, live model refresh, key removal, and what a student sees in chat when the key is wrong or missing.
"""
import os
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

os.environ["MENTOR_STORAGE_DIR"] = tempfile.mkdtemp(prefix="mentor_ui_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

import test_providers as tp  # noqa: E402  (fake multi-vendor API server)
from ai_engine import llm_provider as lp  # noqa: E402
from config import PROVIDER_INFO, settings  # noqa: E402
from database import db  # noqa: E402
from utils import secrets  # noqa: E402


@pytest.fixture(scope="module")
def server():
    tp.reset_state()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), tp.Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture(scope="module")
def app(server):
    import tkinter as tk
    try:
        probe = tk.Tk()
        probe.destroy()
    except tk.TclError:
        pytest.skip("no display available (run under xvfb-run)")
    db.init_db()
    secrets._KEYRING = False
    lp.RETRY_BASE_DELAY = 0
    from interface.app import App
    a = App()
    a.geometry("1300x800+0+0")
    yield a
    a.destroy()


def pump(app, cond=lambda: False, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        app.update()
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def select(view, pid, **fields):
    view.provider_var.set(PROVIDER_INFO[pid]["label"])
    view._load_provider(pid)
    for k, v in fields.items():
        {"model": view.model_var, "url": view.url_var, "key": view.key_var}[k].set(v)


def test_provider_dropdown_lists_every_requested_provider_with_its_own_models(app):
    v = app.views["settings"]
    assert {"openai", "anthropic", "google", "perplexity", "zai", "ollama"} <= set(PROVIDER_INFO)
    seen = {}
    for pid in ("openai", "anthropic", "google", "perplexity", "zai", "ollama"):
        select(v, pid)
        assert v.provider() == pid
        seen[pid] = list(v.model_box.cget("values"))
        assert v.model_var.get() == PROVIDER_INFO[pid]["model"] and PROVIDER_INFO[pid]["label"] == v.provider_var.get()
    assert "gpt-4o-mini" in seen["openai"] and "claude-sonnet-5-5" in seen["anthropic"] and "gemini-2.5-flash" in seen["google"]
    assert "sonar" in seen["perplexity"] and "glm-4.5-air" in seen["zai"]
    assert len({tuple(x) for x in seen.values()}) == 6                                    # the list follows the provider
    select(v, "ollama")
    assert str(v.key_entry.cget("state")) == "disabled" and "optional" in v.hint.cget("text").lower()
    select(v, "openai")
    assert str(v.key_entry.cget("state")) == "normal" and "no model is downloaded" in v.hint.cget("text").lower()
    assert v.key_link.cget("text").endswith(PROVIDER_INFO["openai"]["key_url"])


def test_saving_a_provider_stores_the_key_securely_validates_it_and_shows_status(app, server):
    v = app.views["settings"]
    select(v, "google", model="gemini-2.5-flash", url=f"{server}/google", key=tp.GOOD)
    v._save()
    assert pump(app, lambda: "Connection: OK" in v.conn.cget("text"))
    assert settings.active_provider == "google" and settings.model_for("google") == "gemini-2.5-flash"
    assert secrets.get_key("google") == tp.GOOD and v.key_var.get() == ""                  # key field cleared after saving
    assert "Saved." in v.status.cget("text") and "stored in" in v.status.cget("text")
    assert "AI connected: Google (Gemini)" in app.views["home"].banner.cget("text")
    assert "*" in v.key_info.cget("text") and tp.GOOD not in v.key_info.cget("text")        # masked, never shown in full
    assert [c for c in tp.S["calls"] if c["vendor"] == "ollama"] == []                      # Ollama never contacted


def test_test_connection_uses_the_form_values_without_saving(app, server):
    v = app.views["settings"]
    select(v, "perplexity", url=f"{server}/perplexity", key="definitely-wrong-key")
    before = (settings.active_provider, settings.get("LLM_MODEL"))
    app.test_connection()
    assert pump(app, lambda: "Connection failed" in v.conn.cget("text"))
    assert "rejected the API key" in v.conn.cget("text") and "definitely-wrong-key" not in v.conn.cget("text")
    assert (settings.active_provider, settings.get("LLM_MODEL")) == before and not secrets.has_key("perplexity")   # nothing saved
    v.key_var.set(tp.GOOD)
    app.test_connection()
    assert pump(app, lambda: "Connection OK" in v.conn.cget("text"))


def test_refresh_models_fills_the_dropdown_from_the_account(app, server):
    v = app.views["settings"]
    select(v, "openai", url=f"{server}/openai", key=tp.GOOD)
    app.refresh_models()
    assert pump(app, lambda: "3 model(s) available" in v.conn.cget("text"))                  # wait for the live answer itself
    assert list(v.model_box.cget("values")) == ["gpt-4o", "gpt-4o-mini", "o3-mini"]
    select(v, "zai", url=f"{server}/zai", key=tp.GOOD)
    app.refresh_models()
    assert pump(app, lambda: "does not offer a model list" in v.conn.cget("text"))           # honest when no listing exists


def test_wrong_or_missing_key_gives_a_clear_message_in_chat_and_no_ollama_fallback(app, server, monkeypatch):
    import test_conversation as tc
    v = app.views["settings"]
    select(v, "anthropic", model="claude-sonnet-5-5", url=f"{server}/anthropic", key="wrong-wrong-wrong-1234")
    v._save()
    assert pump(app, lambda: "Connection problem" in v.conn.cget("text") and "rejected the API key" in v.conn.cget("text"))
    assert "AI model not ready" in app.views["home"].banner.cget("text")
    pid, cid = tc.make_project()
    msg = app.mentor.chat(cid, "Why Pandas?")[0]
    assert msg["kind"] == "notice" and "rejected the API key" in msg["content"] and "Settings" in msg["content"]
    assert "wrong-wrong-wrong-1234" not in msg["content"]
    # removing the key -> a different, equally clear message
    from tkinter import messagebox
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    secrets.set_key("anthropic", tp.GOOD)
    app.remove_key("anthropic")
    assert not secrets.has_key("anthropic")
    assert pump(app, lambda: "API key is missing" in app.views["home"].banner.cget("text"))
    msg = app.mentor.chat(cid, "Why Pandas?")[0]
    assert "API key is missing" in msg["content"] and "console.anthropic.com" in msg["content"]
    assert [c for c in tp.S["calls"] if c["vendor"] == "ollama"] == []


def test_the_app_never_selects_ollama_on_its_own():
    settings._overrides.pop("LLM_PROVIDER", None)
    assert settings.active_provider == "openai"                                                # fresh install: cloud, not local
    assert PROVIDER_INFO["ollama"]["label"].endswith("optional)")
