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
    "LLM_PROVIDER": "ollama",  # ollama | openai | anthropic | openai_compatible
    "LLM_MODEL": "",
    "LLM_BASE_URL": "",
    "LLM_API_KEY": "",
    "LLM_TEMPERATURE": "0.4",
    "LLM_TIMEOUT": "180",
    "EMBEDDING_BACKEND": "hash",  # hash | sentence-transformers | ollama
    "EMBEDDING_MODEL": "",
    "THEME": "dark",  # dark | light | system
    "CODE_EXECUTION": "auto",  # auto (only if network isolation exists) | off
}

PROVIDER_DEFAULTS = {
    "ollama": {"model": "llama3.1", "base_url": "http://localhost:11434"},
    "openai": {"model": "gpt-4o-mini", "base_url": "https://api.openai.com/v1"},
    "anthropic": {"model": "claude-sonnet-5-5", "base_url": "https://api.anthropic.com"},
    "openai_compatible": {"model": "", "base_url": "http://localhost:1234/v1"},
}
PROVIDER_KEY_ENV = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}


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

    def provider_value(self, what: str) -> str:
        """Resolve model / base_url / api_key for the active provider."""
        provider = self.get("LLM_PROVIDER")
        if what == "model":
            return self.get("LLM_MODEL") or PROVIDER_DEFAULTS.get(provider, {}).get("model", "")
        if what == "base_url":
            return (self.get("LLM_BASE_URL") or PROVIDER_DEFAULTS.get(provider, {}).get("base_url", "")).rstrip("/")
        if what == "api_key":
            return self.get("LLM_API_KEY") or os.environ.get(PROVIDER_KEY_ENV.get(provider, ""), "")
        return ""

    def update(self, values: dict[str, str]) -> None:
        self._overrides.update({k: str(v) for k, v in values.items()})
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(self._overrides, indent=2), encoding="utf-8")
        try:  # may contain an API key -> owner-only where the OS supports it
            os.chmod(SETTINGS_PATH, 0o600)
        except OSError:
            pass


settings = Settings()
