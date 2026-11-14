"""Provider-agnostic LLM access. Add a provider by subclassing LLMProvider and registering it in PROVIDERS."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import requests

from config import settings

log = logging.getLogger(__name__)


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

    @abstractmethod
    def chat(self, messages: list[dict], temperature: float | None = None, max_tokens: int = 4096,
             json_mode: bool = False) -> str: ...

    def ping(self) -> str:
        """Returns a short success message or raises LLMError/LLMUnavailable."""
        reply = self.chat([{"role": "user", "content": "Reply with the single word: ready"}], max_tokens=16)
        return f"Connected to {self.name} ({self.model}). Model said: {reply.strip()[:40]}"

    def health(self) -> tuple[bool, str]:
        """Cheap configuration check (no tokens spent)."""
        if not self.model:
            return False, "No model configured."
        return True, f"{self.name}: {self.model}"

    # shared HTTP helper with friendly errors
    def _post(self, url: str, payload: dict, headers: dict | None = None) -> dict:
        try:
            resp = requests.post(url, json=payload, headers=headers or {}, timeout=self.timeout)
        except requests.ConnectionError as exc:
            raise LLMUnavailable(f"Cannot reach the {self.name} server at {self.base_url}. "
                                 f"Is it running / is the URL correct? ({exc.__class__.__name__})") from exc
        except requests.Timeout as exc:
            raise LLMUnavailable(f"The {self.name} server timed out after {self.timeout:.0f}s.") from exc
        except requests.RequestException as exc:
            raise LLMUnavailable(f"Network error talking to {self.name}: {exc}") from exc
        if resp.status_code in (401, 403):
            raise LLMError(f"{self.name} rejected the API key (HTTP {resp.status_code}). Check Settings.")
        if resp.status_code == 404:
            raise LLMError(f"{self.name} returned 404 - check the model name '{self.model}' and base URL.")
        if resp.status_code == 429:
            raise LLMUnavailable(f"{self.name} rate limit reached (HTTP 429). Try again shortly.")
        if resp.status_code >= 400:
            raise LLMError(f"{self.name} error HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            return resp.json()
        except ValueError as exc:
            raise LLMError(f"{self.name} returned a non-JSON response.") from exc


class OllamaProvider(LLMProvider):
    name = "Ollama"

    def health(self):
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=4)
            resp.raise_for_status()
            names = [m.get("name", "") for m in resp.json().get("models", [])]
        except requests.RequestException:
            return False, f"Ollama is not reachable at {self.base_url}. Start it with: ollama serve"
        if not any(n == self.model or n.split(":")[0] == self.model.split(":")[0] for n in names):
            return False, f"Ollama is running but model '{self.model}' is not installed (ollama pull {self.model})."
        return True, f"Ollama: {self.model}"

    def chat(self, messages, temperature=None, max_tokens=4096, json_mode=False):
        payload = {"model": self.model, "messages": messages, "stream": False,
                   "options": {"temperature": self.temperature if temperature is None else temperature,
                               "num_predict": max_tokens}}
        if json_mode:
            payload["format"] = "json"
        data = self._post(f"{self.base_url}/api/chat", payload)
        return (data.get("message") or {}).get("content", "")


class OpenAICompatibleProvider(LLMProvider):
    name = "OpenAI-compatible"

    def chat(self, messages, temperature=None, max_tokens=4096, json_mode=False):
        if not self.model:
            raise LLMUnavailable("No model configured. Set LLM_MODEL in Settings.")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {"model": self.model, "messages": messages, "max_tokens": max_tokens,
                   "temperature": self.temperature if temperature is None else temperature}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            data = self._post(f"{self.base_url}/chat/completions", payload, headers)
        except LLMError as exc:
            if json_mode and "HTTP 400" in str(exc):  # server without JSON mode support
                payload.pop("response_format")
                data = self._post(f"{self.base_url}/chat/completions", payload, headers)
            else:
                raise
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Unexpected response shape from the server.") from exc


class OpenAIProvider(OpenAICompatibleProvider):
    name = "OpenAI"

    def health(self):
        return (True, f"OpenAI: {self.model}") if self.api_key else (False, "OpenAI API key missing (Settings).")

    def chat(self, *a, **kw):
        if not self.api_key:
            raise LLMUnavailable("OpenAI API key missing. Add it in Settings or set OPENAI_API_KEY.")
        return super().chat(*a, **kw)


class AnthropicProvider(LLMProvider):
    name = "Anthropic"

    def health(self):
        return (True, f"Anthropic: {self.model}") if self.api_key else (False, "Anthropic API key missing (Settings).")

    def chat(self, messages, temperature=None, max_tokens=4096, json_mode=False):
        if not self.api_key:
            raise LLMUnavailable("Anthropic API key missing. Add it in Settings or set ANTHROPIC_API_KEY.")
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        convo = [m for m in messages if m["role"] != "system"]
        if json_mode:
            system += "\n\nRespond with a single valid JSON value and nothing else."
        payload = {"model": self.model, "max_tokens": max_tokens, "messages": convo,
                   "temperature": self.temperature if temperature is None else temperature}
        if system.strip():
            payload["system"] = system
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        data = self._post(f"{self.base_url}/v1/messages", payload, headers)
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


PROVIDERS = {"ollama": OllamaProvider, "openai": OpenAIProvider, "anthropic": AnthropicProvider,
             "openai_compatible": OpenAICompatibleProvider}

_override: LLMProvider | None = None  # used by tests


def set_provider_override(provider: LLMProvider | None) -> None:
    global _override
    _override = provider


def get_provider() -> LLMProvider:
    if _override is not None:
        return _override
    key = settings.get("LLM_PROVIDER")
    if key not in PROVIDERS:
        raise LLMUnavailable(f"Unknown LLM provider '{key}'. Choose one of: {', '.join(PROVIDERS)}.")
    return PROVIDERS[key]()


def quick_health() -> tuple[bool, str]:
    try:
        return get_provider().health()
    except LLMError as exc:
        return False, str(exc)
