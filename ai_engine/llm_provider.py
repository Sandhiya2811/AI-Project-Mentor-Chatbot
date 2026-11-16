"""Provider-agnostic LLM access. Add a provider by subclassing LLMProvider and registering it in PROVIDERS.

Speed-related behaviour (v2): one shared HTTP session (connection reuse), token streaming for every provider,
Ollama keep-alive + fixed context size (no model reloads), optional warm-up, per-call timing in `last_stats`.
"""
from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Iterator

import requests

from config import settings

log = logging.getLogger(__name__)
_session = requests.Session()  # reused by every provider -> no new TCP/TLS handshake per request


class LLMError(Exception):
    """The LLM answered but something is wrong (bad key, bad model...)."""


class LLMUnavailable(LLMError):
    """The LLM cannot be reached / is not configured. The app keeps its non-AI features."""


class LLMProvider(ABC):
    name = "base"

    def __init__(self) -> None:
        self.model = settings.provider_value("model")
        self.base_url = settings.provider_value("base_url")
        self.api_key = settings.provider_value("api_key")
        self.timeout = float(settings.get("LLM_TIMEOUT") or 180)
        self.temperature = float(settings.get("LLM_TEMPERATURE") or 0.4)
        self.last_stats: dict = {}

    # ---- interface -----------------------------------------------------------------------------
    @abstractmethod
    def chat(self, messages: list[dict], temperature: float | None = None, max_tokens: int = 4096,
             json_mode: bool = False) -> str: ...

    def stream_chat(self, messages: list[dict], temperature: float | None = None, max_tokens: int = 4096,
                    cancel=None) -> Iterator[str]:
        """Yield text pieces as they are generated. Default: no streaming support -> one piece."""
        yield self.chat(messages, temperature, max_tokens)

    def warm_up(self) -> None:
        """Load the model ahead of the first question (only meaningful for local servers)."""

    def ping(self) -> str:
        """Returns a short success message or raises LLMError/LLMUnavailable."""
        reply = self.chat([{"role": "user", "content": "Reply with the single word: ready"}], max_tokens=16)
        return f"Connected to {self.name} ({self.model}). Model said: {reply.strip()[:40]}"

    def health(self) -> tuple[bool, str]:
        """Cheap configuration check (no tokens spent)."""
        if not self.model:
            return False, "No model configured."
        return True, f"{self.name}: {self.model}"

    # ---- shared HTTP helpers with friendly errors ------------------------------------------------
    def _wrap(self, exc: Exception) -> LLMError:
        if isinstance(exc, requests.ConnectionError):
            return LLMUnavailable(f"Cannot reach the {self.name} server at {self.base_url}. "
                                  f"Is it running / is the URL correct? ({exc.__class__.__name__})")
        if isinstance(exc, requests.Timeout):
            return LLMUnavailable(f"The {self.name} server timed out after {self.timeout:.0f}s.")
        return LLMUnavailable(f"Network error talking to {self.name}: {exc}")

    def _check(self, resp: requests.Response) -> None:
        code = resp.status_code
        if code in (401, 403):
            raise LLMError(f"{self.name} rejected the API key (HTTP {code}). Check Settings.")
        if code == 404:
            raise LLMError(f"{self.name} returned 404 - check the model name '{self.model}' and base URL.")
        if code == 429:
            raise LLMUnavailable(f"{self.name} rate limit reached (HTTP 429). Try again shortly.")
        if code >= 400:
            raise LLMError(f"{self.name} error HTTP {code}: {resp.text[:300]}")

    def _post(self, url: str, payload: dict, headers: dict | None = None) -> dict:
        try:
            resp = _session.post(url, json=payload, headers=headers or {}, timeout=(10, self.timeout))
        except requests.RequestException as exc:
            raise self._wrap(exc) from exc
        self._check(resp)
        try:
            return resp.json()
        except ValueError as exc:
            raise LLMError(f"{self.name} returned a non-JSON response.") from exc

    def _stream(self, url: str, payload: dict, headers: dict | None, parse, cancel=None) -> Iterator[str]:
        """POST with stream=True; `parse(line:str) -> str|None` extracts text from one line of the stream."""
        t0 = time.perf_counter()
        first, pieces = None, 0
        self.last_stats = {}
        try:
            resp = _session.post(url, json=payload, headers=headers or {}, stream=True, timeout=(10, self.timeout))
        except requests.RequestException as exc:
            raise self._wrap(exc) from exc
        try:
            self._check(resp)
            for raw in resp.iter_lines(chunk_size=16):  # small reads: never wait for a 512-byte buffer to fill
                if cancel is not None and cancel.is_set():
                    self.last_stats["cancelled"] = True
                    break
                if not raw:
                    continue
                text = parse(raw.decode("utf-8", "replace"))
                if text:
                    if first is None:
                        first = time.perf_counter() - t0
                    pieces += 1
                    yield text
        except requests.RequestException as exc:
            raise self._wrap(exc) from exc
        finally:
            resp.close()  # closing the connection also stops generation on the server
            self.last_stats.update({"ttft_s": first, "total_s": time.perf_counter() - t0, "pieces": pieces})


class OllamaProvider(LLMProvider):
    name = "Ollama"

    def health(self):
        try:
            resp = _session.get(f"{self.base_url}/api/tags", timeout=4)
            resp.raise_for_status()
            names = [m.get("name", "") for m in resp.json().get("models", [])]
        except requests.RequestException:
            return False, f"Ollama is not reachable at {self.base_url}. Start it with: ollama serve"
        if not any(n == self.model or n.split(":")[0] == self.model.split(":")[0] for n in names):
            return False, f"Ollama is running but model '{self.model}' is not installed (ollama pull {self.model})."
        return True, f"Ollama: {self.model}"

    def _payload(self, messages, temperature, max_tokens, stream: bool) -> dict:
        return {"model": self.model, "messages": messages, "stream": stream,
                "keep_alive": settings.get("LLM_KEEP_ALIVE") or "30m",
                "options": {"temperature": self.temperature if temperature is None else temperature,
                            "num_predict": max_tokens, "num_ctx": int(settings.get("LLM_NUM_CTX") or 4096)}}

    def warm_up(self) -> None:
        """Ask Ollama to load the model into memory now (an empty chat request), so the first real question is fast."""
        try:
            self._post(f"{self.base_url}/api/chat", {"model": self.model, "messages": [], "stream": False,
                                                      "keep_alive": settings.get("LLM_KEEP_ALIVE") or "30m",
                                                      "options": {"num_ctx": int(settings.get("LLM_NUM_CTX") or 4096)}})
        except LLMError as exc:
            log.info("Warm-up skipped: %s", exc)

    def chat(self, messages, temperature=None, max_tokens=4096, json_mode=False):
        payload = self._payload(messages, temperature, max_tokens, False)
        if json_mode:
            payload["format"] = "json"
        t0 = time.perf_counter()
        data = self._post(f"{self.base_url}/api/chat", payload)
        self.last_stats = {"total_s": time.perf_counter() - t0, **self._ollama_stats(data)}
        return (data.get("message") or {}).get("content", "")

    @staticmethod
    def _ollama_stats(data: dict) -> dict:
        keys = ("load_duration", "prompt_eval_count", "prompt_eval_duration", "eval_count", "eval_duration")
        return {k: data[k] for k in keys if k in data}

    def stream_chat(self, messages, temperature=None, max_tokens=4096, cancel=None):
        stats: dict = {}

        def parse(line: str):
            try:
                d = json.loads(line)
            except ValueError:
                return None
            if d.get("error"):
                raise LLMError(f"Ollama error: {d['error']}")
            if d.get("done"):
                stats.update(self._ollama_stats(d))
            return (d.get("message") or {}).get("content") or None

        try:
            yield from self._stream(f"{self.base_url}/api/chat", self._payload(messages, temperature, max_tokens, True),
                                    None, parse, cancel)
        finally:
            self.last_stats.update(stats)


class OpenAICompatibleProvider(LLMProvider):
    name = "OpenAI-compatible"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _payload(self, messages, temperature, max_tokens) -> dict:
        return {"model": self.model, "messages": messages, "max_tokens": max_tokens,
                "temperature": self.temperature if temperature is None else temperature}

    def chat(self, messages, temperature=None, max_tokens=4096, json_mode=False):
        if not self.model:
            raise LLMUnavailable("No model configured. Set LLM_MODEL in Settings.")
        payload = self._payload(messages, temperature, max_tokens)
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            data = self._post(f"{self.base_url}/chat/completions", payload, self._headers())
        except LLMError as exc:
            if json_mode and "HTTP 400" in str(exc):  # server without JSON mode support
                payload.pop("response_format")
                data = self._post(f"{self.base_url}/chat/completions", payload, self._headers())
            else:
                raise
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Unexpected response shape from the server.") from exc

    def stream_chat(self, messages, temperature=None, max_tokens=4096, cancel=None):
        if not self.model:
            raise LLMUnavailable("No model configured. Set LLM_MODEL in Settings.")
        payload = self._payload(messages, temperature, max_tokens)
        payload["stream"] = True

        def parse(line: str):
            if not line.startswith("data:"):
                return None
            body = line[5:].strip()
            if body == "[DONE]":
                return None
            try:
                choices = json.loads(body).get("choices") or []
                return (choices[0].get("delta") or {}).get("content") if choices else None
            except ValueError:
                return None

        yield from self._stream(f"{self.base_url}/chat/completions", payload, self._headers(), parse, cancel)


class OpenAIProvider(OpenAICompatibleProvider):
    name = "OpenAI"

    def health(self):
        return (True, f"OpenAI: {self.model}") if self.api_key else (False, "OpenAI API key missing (Settings).")

    def chat(self, *a, **kw):
        if not self.api_key:
            raise LLMUnavailable("OpenAI API key missing. Add it in Settings or set OPENAI_API_KEY.")
        return super().chat(*a, **kw)

    def stream_chat(self, *a, **kw):
        if not self.api_key:
            raise LLMUnavailable("OpenAI API key missing. Add it in Settings or set OPENAI_API_KEY.")
        yield from super().stream_chat(*a, **kw)


class AnthropicProvider(LLMProvider):
    name = "Anthropic"

    def health(self):
        return (True, f"Anthropic: {self.model}") if self.api_key else (False, "Anthropic API key missing (Settings).")

    def _request(self, messages, temperature, max_tokens, json_mode, stream):
        if not self.api_key:
            raise LLMUnavailable("Anthropic API key missing. Add it in Settings or set ANTHROPIC_API_KEY.")
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        convo = [m for m in messages if m["role"] != "system"]
        if json_mode:
            system += "\n\nRespond with a single valid JSON value and nothing else."
        payload = {"model": self.model, "max_tokens": max_tokens, "messages": convo, "stream": stream,
                   "temperature": self.temperature if temperature is None else temperature}
        if system.strip():
            payload["system"] = system
        return payload, {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}

    def chat(self, messages, temperature=None, max_tokens=4096, json_mode=False):
        payload, headers = self._request(messages, temperature, max_tokens, json_mode, False)
        data = self._post(f"{self.base_url}/v1/messages", payload, headers)
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")

    def stream_chat(self, messages, temperature=None, max_tokens=4096, cancel=None):
        payload, headers = self._request(messages, temperature, max_tokens, False, True)

        def parse(line: str):
            if not line.startswith("data:"):
                return None
            try:
                d = json.loads(line[5:].strip())
            except ValueError:
                return None
            if d.get("type") == "error":
                raise LLMError(f"Anthropic error: {(d.get('error') or {}).get('message', 'unknown')}")
            if d.get("type") == "content_block_delta" and (d.get("delta") or {}).get("type") == "text_delta":
                return d["delta"].get("text")
            return None

        yield from self._stream(f"{self.base_url}/v1/messages", payload, headers, parse, cancel)


PROVIDERS = {"ollama": OllamaProvider, "openai": OpenAIProvider, "anthropic": AnthropicProvider,
             "openai_compatible": OpenAICompatibleProvider}

_override: LLMProvider | None = None  # used by tests
_cached: tuple[tuple, LLMProvider] | None = None


def set_provider_override(provider: LLMProvider | None) -> None:
    global _override
    _override = provider


def get_provider() -> LLMProvider:
    """Returns one provider instance per configuration (re-created only when settings change)."""
    global _cached
    if _override is not None:
        return _override
    key = settings.get("LLM_PROVIDER")
    if key not in PROVIDERS:
        raise LLMUnavailable(f"Unknown LLM provider '{key}'. Choose one of: {', '.join(PROVIDERS)}.")
    sig = (key, settings.provider_value("model"), settings.provider_value("base_url"), settings.provider_value("api_key"),
           settings.get("LLM_TEMPERATURE"), settings.get("LLM_TIMEOUT"))
    if _cached is None or _cached[0] != sig:
        _cached = (sig, PROVIDERS[key]())
    return _cached[1]


def quick_health() -> tuple[bool, str]:
    try:
        return get_provider().health()
    except LLMError as exc:
        return False, str(exc)
