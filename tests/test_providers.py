"""Cloud provider integrations, tested against a local server that imitates each vendor's REAL wire format.

What this proves: for every provider the application sends the right URL, authentication header and request body for that
vendor's API, parses normal and streaming responses, validates keys/models, retries transient errors, reports errors
clearly with secrets redacted, and never falls back to Ollama on its own.
What it cannot prove: that the live vendor APIs accept these requests today (that needs real API keys - see
`py main.py --check-providers` / Settings > Test connection).
"""
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

os.environ["MENTOR_STORAGE_DIR"] = tempfile.mkdtemp(prefix="mentor_prov_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from ai_engine import llm_provider as lp  # noqa: E402
from ai_engine.llm_provider import LLMError, LLMUnavailable, build_provider  # noqa: E402
from config import PROVIDER_INFO, settings  # noqa: E402
from utils import secrets  # noqa: E402

GOOD = "good-key-123456789"
S: dict = {}


def reset_state():
    S.clear()
    S.update(calls=[], fail=[], delay=0.0, reject=set(), block=False, echo_key=False)


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    # --- helpers
    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n)) if n else {}

    def _send(self, code, obj, ctype="application/json"):
        raw = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _sse(self, lines):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for ln in lines:
            self.wfile.write((ln + "\n\n").encode())
            self.wfile.flush()

    def _auth_ok(self, vendor):
        h = self.headers
        if vendor == "anthropic":
            return h.get("x-api-key") == GOOD and h.get("anthropic-version")
        if vendor == "google":
            return h.get("x-goog-api-key") == GOOD
        return h.get("Authorization") == f"Bearer {GOOD}"

    def _handle(self, method):
        body = self._body() if method == "POST" else {}
        u = urlparse(self.path)
        parts = u.path.strip("/").split("/", 1)
        vendor, rest = parts[0], "/" + (parts[1] if len(parts) > 1 else "")
        S["calls"].append({"method": method, "vendor": vendor, "path": rest, "query": u.query,
                           "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        if S["delay"]:
            time.sleep(S["delay"])
        if not self._auth_ok(vendor):
            if vendor == "google":
                return self._send(400, {"error": {"message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT"}})
            return self._send(401, {"error": {"message": f"Incorrect API key provided: {self.headers.get('Authorization') or self.headers.get('x-api-key')}"}})
        if S["fail"] and method == "POST":
            code, obj = S["fail"].pop(0)
            return self._send(code, obj)
        if S["reject"] and any(k in body or k in body.get("generationConfig", {}) for k in S["reject"]):
            return self._send(400, {"error": {"message": "Unknown parameter"}})
        if S["echo_key"]:
            return self._send(500, {"error": {"message": f"boom {GOOD}"}})
        stream = bool(body.get("stream")) or "streamGenerateContent" in rest
        if method == "GET":
            return self._get(vendor, rest)
        if vendor in ("openai", "perplexity", "zai") and rest.endswith("/chat/completions"):
            if stream:
                return self._sse([f'data: {json.dumps({"choices": [{"delta": {"content": w}}]})}' for w in ("Hel", "lo ", "there")] + ["data: [DONE]"])
            return self._send(200, {"choices": [{"message": {"content": "Hello there"}}]})
        if vendor == "anthropic" and rest == "/v1/messages":
            if stream:
                return self._sse([f'event: content_block_delta\ndata: {json.dumps({"type": "content_block_delta", "delta": {"type": "text_delta", "text": w}})}' for w in ("Hel", "lo ", "there")])
            return self._send(200, {"content": [{"type": "text", "text": "Hello there"}]})
        if vendor == "google" and ":" in rest:
            if S["block"]:
                return self._send(200, {"promptFeedback": {"blockReason": "SAFETY"}})
            if stream:
                return self._sse([f'data: {json.dumps({"candidates": [{"content": {"parts": [{"text": w}]}}]})}' for w in ("Hel", "lo ", "there")])
            return self._send(200, {"candidates": [{"content": {"parts": [{"text": "Hello there"}]}}]})
        self._send(404, {"error": {"message": "no such route"}})

    def _get(self, vendor, rest):
        if vendor == "openai":
            if rest == "/models":
                return self._send(200, {"data": [{"id": i} for i in ("gpt-4o", "gpt-4o-mini", "text-embedding-3-small", "whisper-1", "gpt-4o-audio-preview", "o3-mini")]})
            return self._send(200, {"id": rest.split("/")[-1]}) if rest.split("/")[-1] in ("gpt-4o-mini", "gpt-5") else self._send(404, {"error": {"message": "The model does not exist"}})
        if vendor == "anthropic":
            if rest == "/v1/models":
                return self._send(200, {"data": [{"id": "claude-sonnet-5-5"}, {"id": "claude-haiku-5-5"}]})
            return self._send(200, {"id": "x"}) if rest.endswith(("claude-sonnet-5-5", "claude-haiku-5-5")) else self._send(404, {"error": {"message": "model not found"}})
        if vendor == "google":
            if rest == "/models":
                return self._send(200, {"models": [{"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
                                                   {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]},
                                                   {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"]}]})
            return self._send(200, {"name": rest}) if rest.endswith(("gemini-2.5-flash", "gemini-2.0-flash")) else self._send(404, {"error": {"message": "model not found"}})
        self._send(404, {"error": {"message": "nope"}})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    reset_state()
    monkeypatch.setattr(lp, "RETRY_BASE_DELAY", 0)
    for names in [v["env"] for v in PROVIDER_INFO.values()]:
        for n in names:
            monkeypatch.delenv(n, raising=False)
    settings._overrides.clear()
    secrets.reset_probe()
    secrets._KEYRING = False          # no real keyring in tests unless a test injects one
    yield
    settings._overrides.clear()


def mk(server, pid, model, key=GOOD, **kw):
    return build_provider(pid, model, f"{server}/{pid}", key, **kw)


MSGS = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"},
        {"role": "user", "content": "q1"}, {"role": "user", "content": "q2"}]


# ------------------------------------------------------------------------------------------------ registry
def test_all_requested_providers_exist_with_models_and_distinct_classes():
    for pid in ("openai", "anthropic", "google", "perplexity", "zai", "ollama"):
        assert pid in lp.PROVIDERS and PROVIDER_INFO[pid]["models"] is not None and PROVIDER_INFO[pid]["label"]
    assert len({lp.PROVIDERS[p] for p in ("openai", "anthropic", "google", "perplexity", "zai", "ollama")}) == 6
    for pid in ("openai", "anthropic", "google", "perplexity", "zai"):
        assert PROVIDER_INFO[pid]["needs_key"] and PROVIDER_INFO[pid]["cloud"] and PROVIDER_INFO[pid]["key_url"].startswith("https://")
    assert settings.active_provider == "openai"            # cloud first: a fresh install does NOT default to Ollama


# ------------------------------------------------------------------------------------------------ OpenAI
def test_openai_chat_and_stream_wire_format(server):
    p = mk(server, "openai", "gpt-4o-mini")
    assert p.chat(MSGS, max_tokens=50) == "Hello there"
    c = S["calls"][-1]
    assert c["path"] == "/chat/completions" and c["headers"]["authorization"] == f"Bearer {GOOD}"
    assert c["body"]["max_tokens"] == 50 and "temperature" in c["body"] and "max_completion_tokens" not in c["body"]
    assert "".join(p.stream_chat(MSGS, max_tokens=50)) == "Hello there"
    assert S["calls"][-1]["body"]["stream"] is True and p.last_stats["ttft_s"] is not None
    p.chat(MSGS, json_mode=True)
    assert S["calls"][-1]["body"]["response_format"] == {"type": "json_object"}


def test_openai_reasoning_models_use_their_own_parameters(server):
    p = mk(server, "openai", "gpt-5-mini")
    p.chat(MSGS, max_tokens=77)
    b = S["calls"][-1]["body"]
    assert b["max_completion_tokens"] == 77 and "max_tokens" not in b and "temperature" not in b
    assert b["reasoning_effort"] == "minimal"


def test_optional_parameters_are_dropped_when_the_server_rejects_them(server):
    S["reject"] = {"reasoning_effort"}
    p = mk(server, "openai", "gpt-5-mini")
    assert p.chat(MSGS) == "Hello there"
    posts = [c for c in S["calls"] if c["method"] == "POST"]
    assert "reasoning_effort" in posts[0]["body"] and "reasoning_effort" not in posts[1]["body"]
    n = len(S["calls"])
    p.chat(MSGS)
    assert len(S["calls"]) == n + 1                              # remembered: no second failed attempt


def test_openai_validate_and_models(server):
    ok, msg = mk(server, "openai", "gpt-4o-mini").validate()
    assert ok and "available" in msg
    assert S["calls"][-1]["method"] == "GET" and S["calls"][-1]["path"] == "/models/gpt-4o-mini"       # no tokens spent
    ok, msg = mk(server, "openai", "no-such-model").validate()
    assert not ok and "404" in msg and "model name" in msg
    assert mk(server, "openai", "gpt-4o-mini").list_models() == ["gpt-4o", "gpt-4o-mini", "o3-mini"]     # chat models only


# ------------------------------------------------------------------------------------------------ Anthropic
def test_anthropic_uses_its_own_format(server):
    p = mk(server, "anthropic", "claude-sonnet-5-5")
    assert p.chat(MSGS, max_tokens=64) == "Hello there"
    c = S["calls"][-1]
    assert c["path"] == "/v1/messages" and c["headers"]["x-api-key"] == GOOD and c["headers"]["anthropic-version"]
    assert "authorization" not in c["headers"]
    assert c["body"]["system"] == "SYS" and all(m["role"] != "system" for m in c["body"]["messages"]) and c["body"]["max_tokens"] == 64
    assert "".join(p.stream_chat(MSGS)) == "Hello there"
    assert p.validate()[0] and S["calls"][-1]["path"] == "/v1/models/claude-sonnet-5-5"
    assert p.list_models() == ["claude-sonnet-5-5", "claude-haiku-5-5"]


# ------------------------------------------------------------------------------------------------ Gemini
def test_gemini_native_api_shape(server):
    p = mk(server, "google", "gemini-2.5-flash")
    assert p.chat(MSGS, max_tokens=99) == "Hello there"
    c = S["calls"][-1]
    assert c["path"] == "/models/gemini-2.5-flash:generateContent" and c["headers"]["x-goog-api-key"] == GOOD
    assert "authorization" not in c["headers"] and "key=" not in c["query"]            # key never in the URL
    b = c["body"]
    assert b["systemInstruction"] == {"parts": [{"text": "SYS"}]}
    assert [m["role"] for m in b["contents"]] == ["user", "model", "user"]             # assistant->model, user turns merged
    assert b["contents"][2]["parts"][0]["text"] == "q1\n\nq2"
    assert b["generationConfig"]["maxOutputTokens"] == 99 and b["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}
    assert "".join(p.stream_chat(MSGS)) == "Hello there"
    assert S["calls"][-1]["path"].endswith(":streamGenerateContent") and S["calls"][-1]["query"] == "alt=sse"
    p.chat(MSGS, json_mode=True)
    assert S["calls"][-1]["body"]["generationConfig"]["responseMimeType"] == "application/json"


def test_gemini_thinking_budget_only_for_models_that_allow_it(server):
    mk(server, "google", "gemini-2.0-flash").chat(MSGS)
    assert "thinkingConfig" not in S["calls"][-1]["body"]["generationConfig"]
    S["reject"] = {"thinkingConfig"}
    p = mk(server, "google", "gemini-2.5-flash")
    assert p.chat(MSGS) == "Hello there"                                                # retried without the parameter


def test_gemini_errors_validation_and_models(server):
    S["block"] = True
    with pytest.raises(LLMError, match="blocked"):
        mk(server, "google", "gemini-2.5-flash").chat(MSGS)
    S["block"] = False
    ok, msg = mk(server, "google", "gemini-2.5-flash", key="wrong").validate()
    assert not ok and "rejected the API key" in msg                                     # Gemini answers HTTP 400 for bad keys
    assert mk(server, "google", "gemini-2.5-flash").validate()[0]
    assert mk(server, "google", "gemini-2.5-flash").list_models() == ["gemini-2.5-flash", "gemini-2.5-pro"]


# ------------------------------------------------------------------------------------------------ Perplexity / Z.ai
def test_perplexity_requires_alternating_roles_and_has_no_json_mode(server):
    p = mk(server, "perplexity", "sonar")
    p.chat(MSGS, json_mode=True)
    b = S["calls"][-1]["body"]
    assert b["messages"][0]["role"] == "system" and b["messages"][1]["role"] == "user"
    non_sys = [m["role"] for m in b["messages"] if m["role"] != "system"]
    assert all(a != b2 for a, b2 in zip(non_sys, non_sys[1:]))                           # strictly alternating
    assert "response_format" not in b and "JSON" in b["messages"][-1]["content"]
    assert b["disable_search"] is True
    assert "".join(p.stream_chat(MSGS)) == "Hello there"
    S["reject"] = {"disable_search"}
    assert mk(server, "perplexity", "sonar").chat(MSGS) == "Hello there"


def test_zai_glm_uses_its_endpoint_and_disables_thinking(server):
    p = mk(server, "zai", "glm-4.5-air")
    assert p.chat(MSGS, json_mode=True) == "Hello there"
    b = S["calls"][-1]["body"]
    assert S["calls"][-1]["path"] == "/chat/completions" and b["thinking"] == {"type": "disabled"}
    assert b["response_format"] == {"type": "json_object"} and S["calls"][-1]["headers"]["authorization"] == f"Bearer {GOOD}"
    assert "".join(p.stream_chat(MSGS)) == "Hello there"
    assert p.validate()[0]                                                                # tiny chat, no models endpoint needed


# ------------------------------------------------------------------------------------------------ keys, errors, retries
def test_missing_key_is_reported_clearly_without_any_network_call(server):
    for pid, label in (("openai", "OpenAI"), ("anthropic", "Anthropic"), ("google", "Google"), ("perplexity", "Perplexity"), ("zai", "Z.ai")):
        p = mk(server, pid, PROVIDER_INFO[pid]["model"], key="")
        ok, msg = p.health()
        assert not ok and label in msg and "API key is missing" in msg and PROVIDER_INFO[pid]["key_url"] in msg
        with pytest.raises(LLMUnavailable, match="API key is missing"):
            p.chat(MSGS)
        with pytest.raises(LLMUnavailable, match="API key is missing"):
            list(p.stream_chat(MSGS))
        assert p.validate()[0] is False
    assert S["calls"] == []


def test_wrong_key_message_and_no_secret_leak(server):
    p = mk(server, "openai", "gpt-4o-mini", key="sk-wrongwrongwrongwrong1234")
    with pytest.raises(LLMError) as e:
        p.chat(MSGS)
    assert "rejected the API key" in str(e.value) and "sk-wrongwrongwrongwrong1234" not in str(e.value)


def test_server_error_echoing_the_key_is_redacted(server):
    S["echo_key"] = True
    secrets._cache["openai"] = GOOD                         # a stored key is masked wherever it appears
    p = build_provider("openai", "gpt-4o-mini", f"{server}/openai", GOOD)
    p.retries = 0
    with pytest.raises(LLMError) as e:
        p.chat(MSGS)
    assert GOOD not in str(e.value) and "***" in str(e.value)


def test_transient_errors_are_retried_but_auth_and_quota_are_not(server):
    S["fail"] = [(503, {"error": {"message": "overloaded"}}), (429, {"error": {"message": "slow down"}})]
    assert mk(server, "anthropic", "claude-sonnet-5-5").chat(MSGS) == "Hello there"
    assert len([c for c in S["calls"] if c["method"] == "POST"]) == 3
    reset_state()
    S["fail"] = [(429, {"error": {"code": "insufficient_quota", "message": "You exceeded your current quota"}})]
    with pytest.raises(LLMUnavailable, match="quota"):
        mk(server, "openai", "gpt-4o-mini").chat(MSGS)
    assert len(S["calls"]) == 1                                                            # no retry on quota
    reset_state()
    S["fail"] = [(503, {})] * 5
    with pytest.raises(LLMUnavailable, match="temporarily unavailable"):
        mk(server, "zai", "glm-4.5-air").chat(MSGS)
    assert len(S["calls"]) == 3                                                            # 1 try + 2 retries, then a clear error


def test_timeout_is_reported_not_hung(server):
    S["delay"] = 1.0
    p = mk(server, "openai", "gpt-4o-mini", timeout=0.3)
    t = time.time()
    with pytest.raises(LLMUnavailable, match="timeout"):
        p.chat(MSGS)
    assert time.time() - t < 3 and len(S["calls"]) == 1                                    # timeouts are not retried


def test_unreachable_cloud_api_never_falls_back_to_ollama(server):
    settings.update({"LLM_PROVIDER": "openai", "BASE_URL_OPENAI": "http://127.0.0.1:9", "BASE_URL_OLLAMA": server + "/ollama",
                     "API_KEY_OPENAI": GOOD})
    secrets.reset_probe(); secrets._KEYRING = False
    p = lp.get_provider()
    assert isinstance(p, lp.OpenAIProvider)
    with pytest.raises(LLMUnavailable, match="Cannot reach OpenAI"):
        p.chat(MSGS)
    with pytest.raises(LLMUnavailable):
        list(p.stream_chat(MSGS))
    assert [c for c in S["calls"] if c["vendor"] == "ollama"] == []                        # Ollama never contacted


# ------------------------------------------------------------------------------------------------ settings / secrets
def test_every_provider_class_is_selectable_from_settings():
    for pid, cls in lp.PROVIDERS.items():
        settings.update({"LLM_PROVIDER": pid})
        lp._cached = None
        assert type(lp.get_provider()) is cls


def test_models_and_urls_are_remembered_per_provider():
    settings.update({"LLM_PROVIDER": "google", "MODEL_GOOGLE": "gemini-2.5-pro", "MODEL_ZAI": "glm-4.6"})
    assert settings.model_for("google") == "gemini-2.5-pro" and settings.model_for("zai") == "glm-4.6"
    assert settings.model_for("perplexity") == "sonar"                                    # default, not another provider's model
    settings.update({"LLM_MODEL": "legacy-model"})
    assert settings.model_for("google") == "gemini-2.5-pro"                               # per-provider value wins
    settings.update({"LLM_PROVIDER": "anthropic"})
    assert settings.model_for("anthropic") == "legacy-model"                              # legacy value belongs to the active provider


def test_keys_are_stored_per_provider_in_the_os_keyring_when_available():
    class FakeKeyring:
        store: dict = {}

        @classmethod
        def get_password(cls, s, u):
            return cls.store.get((s, u))

        @classmethod
        def set_password(cls, s, u, p):
            cls.store[(s, u)] = p

        @classmethod
        def delete_password(cls, s, u):
            cls.store.pop((s, u), None)

        @classmethod
        def get_keyring(cls):
            return cls()
    secrets.reset_probe()
    secrets._KEYRING = FakeKeyring
    where = secrets.set_key("openai", "sk-aaaaaaaaaaaaaaaa1111")
    secrets.set_key("google", "AIzaBBBBBBBBBBBBBBBBBBBB2222")
    assert FakeKeyring.store[("ai-project-mentor", "openai_api_key")] == "sk-aaaaaaaaaaaaaaaa1111"
    assert secrets.get_key("openai") != secrets.get_key("google")
    f = Path(os.environ["MENTOR_STORAGE_DIR"], "settings.json")
    assert "API_KEY_OPENAI" not in settings._overrides and (not f.exists() or "sk-aaaa" not in f.read_text())   # no plain-text copy
    assert "keyring" in where.lower() or "OS" in where
    secrets.delete_key("openai")
    assert secrets.get_key("openai") == "" and secrets.get_key("google").startswith("AIza")


def test_key_falls_back_to_settings_file_without_keyring_and_env_vars_work(monkeypatch):
    secrets.set_key("zai", "zai-key-0123456789")
    assert settings._overrides["API_KEY_ZAI"] == "zai-key-0123456789" and "plain text" in secrets.backend_description()
    assert settings.api_key_for("zai") == "zai-key-0123456789"
    monkeypatch.setenv("GEMINI_API_KEY", "env-gemini-key-000")
    secrets.reset_probe(); secrets._KEYRING = False
    assert settings.api_key_for("google") == "env-gemini-key-000"
    settings.update({"LLM_PROVIDER": "perplexity", "LLM_API_KEY": "legacy-key-abcdefgh"})
    secrets._cache.clear()
    assert settings.api_key_for("perplexity") == "legacy-key-abcdefgh" and settings.api_key_for("openai") == ""   # legacy: active only


def test_log_records_never_contain_keys(caplog):
    import logging
    secrets.install_log_redaction()
    secrets._cache["openai"] = "sk-logsecretlogsecret9999"
    logging.getLogger("x").addFilter(secrets.RedactingFilter())
    with caplog.at_level(logging.INFO):
        logging.getLogger("x").info("calling with %s and Bearer abcdefghijklmnop", "sk-logsecretlogsecret9999")
    assert "sk-logsecret" not in caplog.text and "abcdefghijklmnop" not in caplog.text
