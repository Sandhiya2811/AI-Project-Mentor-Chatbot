"""Central configuration.

Precedence (highest first): storage/settings.json (written by the Settings screen)
-> environment variables / .env -> built-in defaults.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = Path(os.environ.get("MENTOR_STORAGE_DIR") or BASE_DIR / "storage")  # DB, uploads, index, settings
UPLOAD_DIR = STORAGE_DIR / "uploads"
KNOWLEDGE_DIR = BASE_DIR / "storage" / "knowledge"  # bundled + your own reference documents
INDEX_DIR = STORAGE_DIR / "index"
DB_PATH = STORAGE_DIR / "mentor.db"
SETTINGS_PATH = STORAGE_DIR / "settings.json"
ENV_PATH = BASE_DIR / ".env"

APP_NAME = "AI Project Mentor"

# ---- upload / sandbox limits -------------------------------------------------
MAX_UPLOAD_FILE_MB = 25
MAX_SUBMISSION_TOTAL_MB = 60
MAX_FILES_PER_SUBMISSION = 400
MAX_TEXT_CHARS_PER_FILE = 200_000
LLM_CODE_BUDGET_CHARS = 24_000  # how much submitted code is shown to the LLM reviewer
SANDBOX_TIMEOUT_SECONDS = 25
SANDBOX_MEMORY_MB = 1024
MAX_SNIPPET_LINES = 3  # response guard: longest illustrative snippet allowed


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


_load_dotenv(ENV_PATH)

DEFAULTS = {
    "LLM_PROVIDER": "openai",  # openai | anthropic | google | perplexity | zai | ollama (optional, local) | openai_compatible
    "LLM_MODEL": "",
    "LLM_BASE_URL": "",
    "LLM_API_KEY": "",
    "LLM_TEMPERATURE": "0.4",
    "LLM_TIMEOUT": "",  # seconds to wait for a reply; empty = provider default (cloud 60, openai_compatible 120, Ollama 180)
    "EMBEDDING_BACKEND": "hash",  # hash | sentence-transformers | ollama
    "EMBEDDING_MODEL": "",
    "THEME": "dark",  # dark | light | system
    "CODE_EXECUTION": "auto",  # auto (only if network isolation exists) | off
    # --- speed tuning ---
    "LLM_NUM_CTX": "4096",  # Ollama context window (prompts are ~1.5-2.5k tokens); keep it constant so the model is never reloaded
    "LLM_KEEP_ALIVE": "30m",  # Ollama: keep the model in memory between messages
    "CHAT_MAX_TOKENS": "900",  # upper bound for a normal chat answer (roadmap overviews get more)
    "AUTO_AI_NOTES": "idle",  # idle = write AI learning notes in the background only while you are not chatting | off
}

# One entry per provider. To add a provider: add it here and register its class in ai_engine/llm_provider.PROVIDERS.
PROVIDER_INFO = {
    "openai": {
        "label": "OpenAI (ChatGPT)", "cloud": True, "needs_key": True, "model": "gpt-4o-mini",
        "base_url": "https://api.openai.com/v1", "env": ["OPENAI_API_KEY"], "timeout": 60,
        "key_url": "https://platform.openai.com/api-keys",
        "models": ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1", "gpt-4o", "gpt-5-mini", "gpt-5"]},
    "anthropic": {
        "label": "Anthropic (Claude)", "cloud": True, "needs_key": True, "model": "claude-sonnet-5-5",
        "base_url": "https://api.anthropic.com", "env": ["ANTHROPIC_API_KEY"], "timeout": 60,
        "key_url": "https://console.anthropic.com/settings/keys",
        "models": ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]},
    "google": {
        "label": "Google (Gemini)", "cloud": True, "needs_key": True, "model": "gemini-2.5-flash",
        "base_url": "https://generativelanguage.googleapis.com/v1beta", "env": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "timeout": 60, "key_url": "https://aistudio.google.com/app/apikey",
        "models": ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro", "gemini-2.0-flash"]},
    "perplexity": {
        "label": "Perplexity AI", "cloud": True, "needs_key": True, "model": "sonar",
        "base_url": "https://api.perplexity.ai", "env": ["PERPLEXITY_API_KEY", "PPLX_API_KEY"], "timeout": 60,
        "key_url": "https://www.perplexity.ai/settings/api",
        "models": ["sonar", "sonar-pro", "sonar-reasoning-pro"]},
    "zai": {
        "label": "Z.ai (GLM)", "cloud": True, "needs_key": True, "model": "glm-4.5-air",
        "base_url": "https://api.z.ai/api/paas/v4", "env": ["ZAI_API_KEY", "ZHIPUAI_API_KEY"], "timeout": 60,
        "key_url": "https://z.ai/manage-apikey/apikey-list",
        "models": ["glm-4.5-air", "glm-4.5", "glm-4.5-flash", "glm-4.6"]},
    "ollama": {
        "label": "Ollama (local, optional)", "cloud": False, "needs_key": False, "model": "llama3.1",
        "base_url": "http://localhost:11434", "env": [], "timeout": 180, "key_url": "",
        "models": ["llama3.2:3b", "llama3.1", "qwen2.5:7b"]},
    "openai_compatible": {
        "label": "OpenAI-compatible (custom server)", "cloud": False, "needs_key": False, "model": "",
        "base_url": "http://localhost:1234/v1", "env": [], "timeout": 120, "key_url": "", "models": []},
}
# Backwards-compatible views of the registry (older code and tests import these names).
PROVIDER_DEFAULTS = {k: {"model": v["model"], "base_url": v["base_url"]} for k, v in PROVIDER_INFO.items()}
PROVIDER_KEY_ENV = {k: v["env"][0] for k, v in PROVIDER_INFO.items() if v["env"]}


class Settings:
    def __init__(self) -> None:
        self._overrides: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        self._overrides = {}
        if SETTINGS_PATH.exists():
            try:
                self._overrides = {k: str(v) for k, v in json.loads(SETTINGS_PATH.read_text("utf-8")).items()}
            except (OSError, ValueError):
                self._overrides = {}

    def get(self, key: str) -> str:
        if key in self._overrides:
            return self._overrides[key]
        if os.environ.get(key):
            return os.environ[key]
        return DEFAULTS.get(key, "")

    # ---- per-provider values --------------------------------------------------------------------
    @property
    def active_provider(self) -> str:
        return self.get("LLM_PROVIDER") or "openai"

    def model_for(self, provider: str) -> str:
        """Saved model of `provider`. The legacy single LLM_MODEL belongs to the provider that is currently active."""
        saved = self._overrides.get(f"MODEL_{provider.upper()}", "")
        if not saved and provider == self.active_provider:
            saved = self.get("LLM_MODEL")
        return saved or PROVIDER_INFO.get(provider, {}).get("model", "")

    def base_url_for(self, provider: str) -> str:
        saved = self._overrides.get(f"BASE_URL_{provider.upper()}", "")
        if not saved and provider == self.active_provider:
            saved = self.get("LLM_BASE_URL")
        return (saved or PROVIDER_INFO.get(provider, {}).get("base_url", "")).rstrip("/")

    def api_key_for(self, provider: str) -> str:
        from utils import secrets   # local import: secrets reads this module
        return secrets.get_key(provider)

    def timeout_for(self, provider: str) -> float:
        raw = self.get("LLM_TIMEOUT")
        try:
            return float(raw) if raw else float(PROVIDER_INFO.get(provider, {}).get("timeout", 120))
        except ValueError:
            return float(PROVIDER_INFO.get(provider, {}).get("timeout", 120))

    def provider_value(self, what: str) -> str:
        """Resolve model / base_url / api_key for the ACTIVE provider (kept for existing callers)."""
        p = self.active_provider
        return {"model": self.model_for, "base_url": self.base_url_for, "api_key": self.api_key_for}.get(what, lambda _p: "")(p)

    def remove(self, keys: list[str]) -> None:
        changed = False
        for k in keys:
            changed |= self._overrides.pop(k, None) is not None
        if changed:
            self._write()

    def update(self, values: dict[str, str]) -> None:
        self._overrides.update({k: str(v) for k, v in values.items()})
        self._write()

    def _write(self) -> None:
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(self._overrides, indent=2), encoding="utf-8")
        try:  # may contain a fallback-stored API key -> owner-only where the OS supports it
            os.chmod(SETTINGS_PATH, 0o600)
        except OSError:
            pass


settings = Settings()
