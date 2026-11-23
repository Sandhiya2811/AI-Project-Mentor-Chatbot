"""Provider-agnostic LLM access. Cloud APIs are the primary option; Ollama is optional and only used when selected.

Add a provider: subclass LLMProvider, add it to PROVIDERS here and to PROVIDER_INFO in config.py (label, default model,
base URL, key URL, model list). Each provider speaks its own official HTTP API - they are NOT interchangeable:

  openai      POST {base}/chat/completions        Bearer key          (reasoning models: max_completion_tokens, no temperature)
  anthropic   POST {base}/v1/messages             x-api-key + anthropic-version, system prompt as a separate field
  google      POST {base}/models/{m}:generateContent | :streamGenerateContent?alt=sse   x-goog-api-key,
              systemInstruction + contents(role user/model)
  perplexity  POST {base}/chat/completions        Bearer key, strictly alternating roles (Sonar models)
  zai         POST {base}/chat/completions        Bearer key (GLM models, OpenAI-style schema)
  ollama      POST {base}/api/chat                no key, NDJSON stream (local, optional - never used as a silent fallback)

Behaviour shared by all: one HTTP session (connection reuse), token streaming, retries with back-off for transient errors
(429/5xx, dropped connections) on cloud providers only, friendly error messages with secrets redacted, key/model validation
without spending tokens where the API allows it, per-call timing in `last_stats`.
"""
from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Iterator

import requests

from config import PROVIDER_INFO, settings
from utils import secrets

log = logging.getLogger(__name__)
_session = requests.Session()  # reused by every provider -> no new TCP/TLS handshake per request
TRANSIENT = {429, 500, 502, 503, 504, 529}
RETRY_BASE_DELAY = 0.8        # seconds; doubled per attempt (tests set it to 0)


class LLMError(Exception):
    """The LLM answered but something is wrong (bad key, bad model...)."""


class LLMUnavailable(LLMError):
    """The LLM cannot be reached / is not configured. The app keeps its non-AI features."""


class LLMProvider(ABC):
    id = "base"
    name = "base"

    def __init__(self, provider_id: str | None = None, model: str | None = None, base_url: str | None = None,
                 api_key: str | None = None, timeout: float | None = None) -> None:
        pid = provider_id or self.id
        info = PROVIDER_INFO.get(pid, {})
        self.model = (model if model is not None else settings.model_for(pid)).strip()
        self.base_url = (base_url if base_url is not None else settings.base_url_for(pid)).strip().rstrip("/")
        self.api_key = (api_key if api_key is not None else settings.api_key_for(pid)).strip()
        self.timeout = float(timeout or settings.timeout_for(pid))
        self.temperature = float(settings.get("LLM_TEMPERATURE") or 0.4)
        self.retries = 2 if info.get("cloud") else 0
        self.last_stats: dict = {}
        self._no_optional = False       # set when the server rejected our optional speed-up parameters

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

    def list_models(self) -> list[str]:
        """Models the account can use (live). [] when the provider has no listing endpoint. May raise LLMError."""
        return []

    def _validate(self) -> str:
        """Provider-specific check of key + model. Default: a 1-word chat. Raises LLMError on failure."""
        self.chat([{"role": "user", "content": "ping"}], max_tokens=8)
        return f"Connected to {self.name} ({self.model})."

    def validate(self) -> tuple[bool, str]:
        """Check the key and the model. Never raises; returns (ok, human-readable message)."""
        try:
            self._require_key()
            return True, self._validate()
        except LLMError as exc:
            return False, str(exc)
        except Exception as exc:  # noqa: BLE001 - the UI must always get a message
            return False, secrets.redact(f"Unexpected error while checking {self.name}: {exc}")

    def health(self) -> tuple[bool, str]:
        """Cheap configuration check (no network, no tokens)."""
        try:
            self._require_key()
        except LLMUnavailable as exc:
            return False, str(exc)
        if not self.model:
            return False, f"No model selected for {self.name}. Choose one in Settings."
        return True, f"{self.name}: {self.model}"

    # ---- keys ------------------------------------------------------------------------------------
    def missing_key_message(self) -> str:
        info = PROVIDER_INFO.get(self.id, {})
        url = f" Get a key at {info['key_url']}" if info.get("key_url") else ""
        return (f"{info.get('label', self.name)} API key is missing. Open Settings > AI model, select this provider, "
                f"paste your key and press Save (or set {', '.join(info.get('env') or ['an environment variable'])}).{url}")

    def _require_key(self) -> None:
        if PROVIDER_INFO.get(self.id, {}).get("needs_key") and not self.api_key:
            raise LLMUnavailable(self.missing_key_message())

    # ---- shared HTTP helpers with friendly errors ------------------------------------------------
    def _wrap(self, exc: Exception) -> LLMError:
        if isinstance(exc, requests.ConnectionError):
            if PROVIDER_INFO.get(self.id, {}).get("cloud"):
                return LLMUnavailable(f"Cannot reach {self.name} at {self.base_url}. Check your internet connection, "
                                      f"proxy or firewall. ({exc.__class__.__name__})")
            return LLMUnavailable(f"Cannot reach the {self.name} server at {self.base_url}. "
                                  f"Is it running / is the URL correct? ({exc.__class__.__name__})")
        if isinstance(exc, requests.Timeout):
            return LLMUnavailable(f"{self.name} did not answer within {self.timeout:.0f}s (timeout). Try again, pick a "
                                  "faster model, or raise LLM_TIMEOUT.")
        return LLMUnavailable(secrets.redact(f"Network error talking to {self.name}: {exc}"))

    @staticmethod
    def _detail(resp: requests.Response) -> str:
        try:
            j = resp.json()
            err = j.get("error", j) if isinstance(j, dict) else j
            msg = err.get("message") or err.get("detail") or err.get("status") if isinstance(err, dict) else str(err)
        except ValueError:
            msg = resp.text
        return secrets.redact(str(msg or "")[:300])

    def _check(self, resp: requests.Response) -> None:
        code = resp.status_code
        if code < 400:
            return
        detail = self._detail(resp)
        low = (resp.text or "")[:600].lower()
        if code in (401, 403) or (code == 400 and ("api key not valid" in low or "api_key_invalid" in low)):
            raise LLMError(f"{self.name} rejected the API key (HTTP {code}). Check the key in Settings. {detail}".strip())
        if code == 404:
            raise LLMError(f"{self.name} returned 404 - check the model name '{self.model}' and the base URL. {detail}".strip())
        if code == 429:
            if any(w in low for w in ("insufficient_quota", "quota", "billing", "credit")):
                raise LLMUnavailable(f"{self.name}: quota / billing limit reached (HTTP 429). Check your plan and credit. {detail}".strip())
            raise LLMUnavailable(f"{self.name} rate limit reached (HTTP 429). Wait a moment and try again. {detail}".strip())
        if code >= 500:
            raise LLMUnavailable(f"{self.name} is temporarily unavailable (HTTP {code}). Try again shortly. {detail}".strip())
        raise LLMError(f"{self.name} error HTTP {code}: {detail}")

    def _send(self, url: str, payload: dict | None, headers: dict | None, stream: bool = False) -> requests.Response:
        """One request with retries for transient failures (cloud providers only). Never retries timeouts."""
        self._require_key()
        attempt = 0
        while True:
            try:
                if payload is None:
                    resp = _session.get(url, headers=headers or {}, timeout=(10, self.timeout))
                else:
                    resp = _session.post(url, json=payload, headers=headers or {}, stream=stream, timeout=(10, self.timeout))
            except requests.ConnectionError as exc:
                if attempt < self.retries:
                    time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                    attempt += 1
                    continue
                raise self._wrap(exc) from exc
            except requests.RequestException as exc:
                raise self._wrap(exc) from exc
            if resp.status_code in TRANSIENT and attempt < self.retries and "insufficient_quota" not in (resp.text or "")[:600]:
                try:
                    delay = min(float(resp.headers.get("Retry-After", "")), 5.0)
                except ValueError:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                resp.close()
                time.sleep(delay)
                attempt += 1
                continue
            return resp

    def _post(self, url: str, payload: dict, headers: dict | None = None) -> dict:
        resp = self._send(url, payload, headers)
        self._check(resp)
        try:
            return resp.json()
        except ValueError as exc:
            raise LLMError(f"{self.name} returned a non-JSON response.") from exc

    def _get(self, url: str, headers: dict | None = None) -> dict:
        resp = self._send(url, None, headers)
        self._check(resp)
        try:
            return resp.json()
        except ValueError as exc:
            raise LLMError(f"{self.name} returned a non-JSON response.") from exc

    def _post_optional(self, url: str, payload: dict, optional: dict, headers: dict | None = None) -> dict:
        """POST with optional speed-up parameters; if the server answers HTTP 400, retry once without them."""
        if optional and not self._no_optional:
            try:
                return self._post(url, {**payload, **optional}, headers)
            except LLMError as exc:
                if "HTTP 400" not in str(exc):
                    raise
                self._no_optional = True
                log.info("%s rejected optional parameters %s - continuing without them", self.name, list(optional))
        return self._post(url, payload, headers)

    def _stream(self, url: str, payload: dict, headers: dict | None, parse, cancel=None) -> Iterator[str]:
        """POST with stream=True; `parse(line:str) -> str|None` extracts text from one line of the stream."""
        t0 = time.perf_counter()
        first, pieces = None, 0
        self.last_stats = {}
        resp = self._send(url, payload, headers, stream=True)
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

    def _stream_optional(self, url, payload, optional, headers, parse, cancel=None) -> Iterator[str]:
        use = optional if (optional and not self._no_optional) else {}
        started = False
        try:
            for piece in self._stream(url, {**payload, **use}, headers, parse, cancel):
                started = True
                yield piece
        except LLMError as exc:
            if use and not started and "HTTP 400" in str(exc):
                self._no_optional = True
                log.info("%s rejected optional parameters %s - continuing without them", self.name, list(use))
                yield from self._stream(url, payload, headers, parse, cancel)
            else:
                raise


class OllamaProvider(LLMProvider):
    id = "ollama"
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

    def _validate(self) -> str:
        ok, msg = self.health()
        if not ok:
            raise LLMUnavailable(msg)
        return f"Connected to {msg}"

    def list_models(self) -> list[str]:
        try:
            resp = _session.get(f"{self.base_url}/api/tags", timeout=4)
            resp.raise_for_status()
            return sorted(m.get("name", "") for m in resp.json().get("models", []) if m.get("name"))
        except requests.RequestException as exc:
            raise self._wrap(exc) from exc

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
    """Base for every server that speaks the OpenAI 'chat/completions' schema (OpenAI, Perplexity, Z.ai, LM Studio...)."""
    id = "openai_compatible"
    name = "OpenAI-compatible"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _payload(self, messages, temperature, max_tokens) -> dict:
        return {"model": self.model, "messages": self._prepare(messages), "max_tokens": max_tokens,
                "temperature": self.temperature if temperature is None else temperature}

    def _prepare(self, messages: list[dict]) -> list[dict]:
        return messages

    def _optional(self, json_mode: bool) -> dict:
        """Parameters that speed things up or enable JSON mode; dropped automatically if the server answers HTTP 400."""
        return {"response_format": {"type": "json_object"}} if json_mode else {}

    def _need_model(self) -> None:
        if not self.model:
            raise LLMUnavailable(f"No model selected for {self.name}. Choose one in Settings.")

    def chat(self, messages, temperature=None, max_tokens=4096, json_mode=False):
        self._need_model()
        data = self._post_optional(f"{self.base_url}/chat/completions", self._payload(messages, temperature, max_tokens),
                                   self._optional(json_mode), self._headers())
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Unexpected response shape from the server.") from exc

    def stream_chat(self, messages, temperature=None, max_tokens=4096, cancel=None):
        self._need_model()
        payload = self._payload(messages, temperature, max_tokens)
        payload["stream"] = True

        def parse(line: str):
            if not line.startswith("data:"):
                return None
            body = line[5:].strip()
            if body == "[DONE]":
                return None
            try:
                d = json.loads(body)
            except ValueError:
                return None
            if d.get("error"):
                raise LLMError(f"{self.name} error: {secrets.redact(str(d['error'])[:200])}")
            choices = d.get("choices") or []
            return (choices[0].get("delta") or {}).get("content") if choices else None

        yield from self._stream_optional(f"{self.base_url}/chat/completions", payload, self._optional(False),
                                         self._headers(), parse, cancel)


class OpenAIProvider(OpenAICompatibleProvider):
    """OpenAI Chat Completions API. Reasoning models (gpt-5*, o-series) need max_completion_tokens and no temperature."""
    id = "openai"
    name = "OpenAI"

    def _reasoning(self) -> bool:
        return self.model.lower().startswith(("gpt-5", "o1", "o3", "o4"))

    def _payload(self, messages, temperature, max_tokens) -> dict:
        p = super()._payload(messages, temperature, max_tokens)
        if self._reasoning():
            p.pop("temperature", None)
            p["max_completion_tokens"] = p.pop("max_tokens")
        return p

    def _optional(self, json_mode: bool) -> dict:
        o = super()._optional(json_mode)
        m = self.model.lower()
        if m.startswith("gpt-5"):
            o["reasoning_effort"] = "minimal"      # short, fast answers for a chat mentor
        elif m.startswith(("o1", "o3", "o4")):
            o["reasoning_effort"] = "low"
        return o

    def _validate(self) -> str:
        self._need_model()
        self._get(f"{self.base_url}/models/{self.model}", self._headers())    # checks key AND model, spends no tokens
        return f"Connected to OpenAI. Model '{self.model}' is available."

    def list_models(self) -> list[str]:
        ids = [m.get("id", "") for m in self._get(f"{self.base_url}/models", self._headers()).get("data", [])]
        skip = ("audio", "realtime", "transcribe", "tts", "image", "embedding", "search", "moderation", "instruct", "whisper", "dall")
        keep = [i for i in ids if i.startswith(("gpt-", "o1", "o3", "o4", "chatgpt")) and not any(s in i for s in skip)]
        return sorted(set(keep))


class PerplexityProvider(OpenAICompatibleProvider):
    """Perplexity Sonar API (OpenAI-style schema, but roles must alternate user/assistant and there is no JSON mode)."""
    id = "perplexity"
    name = "Perplexity"

    def _prepare(self, messages):
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        merged: list[dict] = []
        for m in messages:
            if m["role"] == "system":
                continue
            if merged and merged[-1]["role"] == m["role"]:
                merged[-1] = {"role": m["role"], "content": merged[-1]["content"] + "\n\n" + m["content"]}
            else:
                merged.append({"role": m["role"], "content": m["content"]})
        while merged and merged[0]["role"] != "user":
            merged.pop(0)
        return ([{"role": "system", "content": system}] if system.strip() else []) + merged

    def _optional(self, json_mode: bool) -> dict:
        return {"disable_search": True}            # a mentor answers from the model; web search would only add latency

    def chat(self, messages, temperature=None, max_tokens=4096, json_mode=False):
        if json_mode:                              # Perplexity supports only JSON *schemas*; ask in the prompt instead
            messages = messages + [{"role": "user", "content": "Respond with a single valid JSON value and nothing else."}]
        return super().chat(messages, temperature, max_tokens, False)


class ZaiProvider(OpenAICompatibleProvider):
    """Z.ai (Zhipu) GLM models through the OpenAI-style endpoint https://api.z.ai/api/paas/v4/chat/completions."""
    id = "zai"
    name = "Z.ai GLM"

    def _optional(self, json_mode: bool) -> dict:
        o = super()._optional(json_mode)
        o["thinking"] = {"type": "disabled"}       # GLM-4.5+ otherwise "thinks" first, which delays the first visible word
        return o


class AnthropicProvider(LLMProvider):
    id = "anthropic"
    name = "Anthropic"

    def _headers(self) -> dict:
        return {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}

    def _request(self, messages, temperature, max_tokens, json_mode, stream):
        self._require_key()
        if not self.model:
            raise LLMUnavailable("No model selected for Anthropic. Choose one in Settings.")
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        convo = [m for m in messages if m["role"] != "system"]
        if json_mode:
            system += "\n\nRespond with a single valid JSON value and nothing else."
        payload = {"model": self.model, "max_tokens": max_tokens, "messages": convo, "stream": stream,
                   "temperature": self.temperature if temperature is None else temperature}
        if system.strip():
            payload["system"] = system
        return payload, self._headers()

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
                raise LLMError(f"Anthropic error: {secrets.redact((d.get('error') or {}).get('message', 'unknown'))}")
            if d.get("type") == "content_block_delta" and (d.get("delta") or {}).get("type") == "text_delta":
                return d["delta"].get("text")
            return None

        yield from self._stream(f"{self.base_url}/v1/messages", payload, headers, parse, cancel)

    def _validate(self) -> str:
        self._get(f"{self.base_url}/v1/models/{self.model}", self._headers())
        return f"Connected to Anthropic. Model '{self.model}' is available."

    def list_models(self) -> list[str]:
        data = self._get(f"{self.base_url}/v1/models?limit=100", self._headers())
        return [m["id"] for m in data.get("data", []) if m.get("id")]


class GeminiProvider(LLMProvider):
    """Google Gemini API (generativelanguage.googleapis.com). Its own schema: systemInstruction + contents/parts,
    roles 'user' and 'model', key in the x-goog-api-key header, SSE streaming via :streamGenerateContent?alt=sse."""
    id = "google"
    name = "Google Gemini"

    def _path(self) -> str:
        return self.model if self.model.startswith("models/") else f"models/{self.model}"

    def _headers(self) -> dict:
        return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

    def _fast_thinking(self) -> bool:
        return "2.5-flash" in self.model.lower() and not self._no_optional    # 2.5 Flash may switch 'thinking' off

    def _body(self, messages, temperature, max_tokens, json_mode) -> dict:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        contents: list[dict] = []
        for m in messages:
            if m["role"] == "system":
                continue
            role = "model" if m["role"] == "assistant" else "user"
            if contents and contents[-1]["role"] == role:        # Gemini expects alternating turns
                contents[-1]["parts"][0]["text"] += "\n\n" + m["content"]
            else:
                contents.append({"role": role, "parts": [{"text": m["content"]}]})
        if not contents or contents[0]["role"] != "user":
            contents.insert(0, {"role": "user", "parts": [{"text": "Hello"}]})
        gen: dict = {"temperature": self.temperature if temperature is None else temperature, "maxOutputTokens": max_tokens}
        if json_mode:
            gen["responseMimeType"] = "application/json"
        if self._fast_thinking():
            gen["thinkingConfig"] = {"thinkingBudget": 0}
        body: dict = {"contents": contents, "generationConfig": gen}
        if system.strip():
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return body

    @staticmethod
    def _text(data: dict) -> str:
        cands = data.get("candidates") or []
        if not cands:
            reason = (data.get("promptFeedback") or {}).get("blockReason")
            raise LLMError("Gemini returned no answer" + (f" (the request was blocked: {reason})." if reason else "."))
        text = "".join(p.get("text", "") for p in (cands[0].get("content") or {}).get("parts", []) if not p.get("thought"))
        if not text and cands[0].get("finishReason") in ("SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT"):
            raise LLMError("Gemini blocked this answer with its safety filters.")
        return text

    def chat(self, messages, temperature=None, max_tokens=4096, json_mode=False):
        self._require_key()
        url = f"{self.base_url}/{self._path()}:generateContent"
        try:
            data = self._post(url, self._body(messages, temperature, max_tokens, json_mode), self._headers())
        except LLMError as exc:
            if "HTTP 400" not in str(exc) or self._no_optional:
                raise
            self._no_optional = True       # most likely the thinkingConfig parameter: retry without it
            data = self._post(url, self._body(messages, temperature, max_tokens, json_mode), self._headers())
        return self._text(data)

    def stream_chat(self, messages, temperature=None, max_tokens=4096, cancel=None):
        self._require_key()
        url = f"{self.base_url}/{self._path()}:streamGenerateContent?alt=sse"

        def parse(line: str):
            if not line.startswith("data:"):
                return None
            try:
                d = json.loads(line[5:].strip())
            except ValueError:
                return None
            if d.get("error"):
                raise LLMError(f"Gemini error: {secrets.redact(str((d['error'] or {}).get('message', d['error']))[:200])}")
            try:
                return self._text(d) or None
            except LLMError:
                if (d.get("promptFeedback") or {}).get("blockReason"):
                    raise
                return None

        started = False
        try:
            for piece in self._stream(url, self._body(messages, temperature, max_tokens, False), self._headers(), parse, cancel):
                started = True
                yield piece
        except LLMError as exc:
            if started or "HTTP 400" not in str(exc) or self._no_optional:
                raise
            self._no_optional = True
            yield from self._stream(url, self._body(messages, temperature, max_tokens, False), self._headers(), parse, cancel)

    def _validate(self) -> str:
        if not self.model:
            raise LLMUnavailable("No model selected for Gemini. Choose one in Settings.")
        self._get(f"{self.base_url}/{self._path()}", self._headers())
        return f"Connected to Google Gemini. Model '{self.model}' is available."

    def list_models(self) -> list[str]:
        data = self._get(f"{self.base_url}/models?pageSize=200", self._headers())
        out = [m["name"].split("/", 1)[-1] for m in data.get("models", [])
               if "generateContent" in m.get("supportedGenerationMethods", []) and "gemini" in m.get("name", "")]
        return sorted(set(out))


PROVIDERS = {"openai": OpenAIProvider, "anthropic": AnthropicProvider, "google": GeminiProvider,
             "perplexity": PerplexityProvider, "zai": ZaiProvider, "ollama": OllamaProvider,
             "openai_compatible": OpenAICompatibleProvider}

_override: LLMProvider | None = None  # used by tests
_cached: tuple[tuple, LLMProvider] | None = None


def set_provider_override(provider: LLMProvider | None) -> None:
    global _override
    _override = provider


def build_provider(provider_id: str, model: str | None = None, base_url: str | None = None,
                   api_key: str | None = None, timeout: float | None = None) -> LLMProvider:
    """A provider for explicit values (Settings 'Test connection' uses the values typed in the form, before saving)."""
    if provider_id not in PROVIDERS:
        raise LLMUnavailable(f"Unknown LLM provider '{provider_id}'. Choose one of: {', '.join(PROVIDERS)}.")
    return PROVIDERS[provider_id](provider_id, model, base_url, api_key, timeout)


def get_provider() -> LLMProvider:
    """One provider instance per configuration (re-created only when settings change). NEVER switches provider by itself:
    if the selected cloud API fails the student sees the error - there is no silent fallback to Ollama."""
    global _cached
    if _override is not None:
        return _override
    key = settings.active_provider
    if key not in PROVIDERS:
        raise LLMUnavailable(f"Unknown LLM provider '{key}'. Choose one of: {', '.join(PROVIDERS)}.")
    sig = (key, settings.model_for(key), settings.base_url_for(key), settings.api_key_for(key),
           settings.get("LLM_TEMPERATURE"), settings.get("LLM_TIMEOUT"))
    if _cached is None or _cached[0] != sig:
        _cached = (sig, PROVIDERS[key](key))
    return _cached[1]


def quick_health() -> tuple[bool, str]:
    """Configuration check without network access (key present? model chosen?)."""
    try:
        return get_provider().health()
    except LLMError as exc:
        return False, str(exc)


def connection_status() -> tuple[bool, str]:
    """Real check with the provider's API (key + model). Used at start-up and by Settings > Test connection."""
    try:
        return get_provider().validate()
    except LLMError as exc:
        return False, str(exc)
