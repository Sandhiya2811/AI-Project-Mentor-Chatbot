"""The real OllamaProvider against a local fake Ollama server (slow token stream). Proves: first text arrives long before
the full answer is finished, request parameters (keep_alive, num_ctx, num_predict) are sent, errors are friendly."""
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

os.environ["MENTOR_STORAGE_DIR"] = tempfile.mkdtemp(prefix="mentor_stream_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from ai_engine.llm_provider import LLMUnavailable, OllamaProvider  # noqa: E402
from config import settings  # noqa: E402

SEEN: list[dict] = []
DELAY = 0.15


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.append(body)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        if not body.get("stream"):
            self.wfile.write(json.dumps({"message": {"content": "whole answer"}, "done": True}).encode())
            return
        for w in ["one ", "two ", "three ", "four ", "five "]:
            time.sleep(DELAY)
            self.wfile.write((json.dumps({"message": {"content": w}, "done": False}) + "\n").encode())
            self.wfile.flush()
        self.wfile.write((json.dumps({"message": {"content": ""}, "done": True, "eval_count": 5, "eval_duration": 750_000_000,
                                      "prompt_eval_count": 40, "prompt_eval_duration": 100_000_000,
                                      "load_duration": 5_000_000}) + "\n").encode())


@pytest.fixture(scope="module")
def server():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    settings.update({"LLM_PROVIDER": "ollama", "LLM_BASE_URL": f"http://127.0.0.1:{srv.server_port}", "LLM_MODEL": "m"})
    yield srv
    srv.shutdown()


def test_first_text_arrives_before_the_answer_is_complete(server):
    llm = OllamaProvider()
    t0, first, pieces = time.perf_counter(), None, []
    for p in llm.stream_chat([{"role": "user", "content": "hi"}], max_tokens=50):
        first = first or time.perf_counter() - t0
        pieces.append(p)
    total = time.perf_counter() - t0
    assert "".join(pieces) == "one two three four five "
    assert first < total / 2 and first < 0.5                         # visible long before completion
    assert llm.last_stats["ttft_s"] == pytest.approx(first, abs=0.1)
    assert llm.last_stats["eval_count"] == 5 and llm.last_stats["load_duration"] == 5_000_000


def test_speed_parameters_are_sent(server):
    SEEN.clear()
    list(OllamaProvider().stream_chat([{"role": "user", "content": "hi"}], max_tokens=222))
    body = SEEN[-1]
    assert body["stream"] is True and body["keep_alive"] == "30m"
    assert body["options"]["num_predict"] == 222 and body["options"]["num_ctx"] == 4096


def test_connection_error_is_friendly():
    settings.update({"LLM_BASE_URL": "http://127.0.0.1:9"})
    with pytest.raises(LLMUnavailable) as e:
        list(OllamaProvider().stream_chat([{"role": "user", "content": "hi"}]))
    assert "Cannot reach" in str(e.value)
