"""API-key storage and redaction.

Where a key lives (first match wins when reading):
  1. the operating-system credential store through the optional `keyring` package
     (Windows Credential Manager, macOS Keychain, Secret Service on Linux)  <- used when available
  2. `storage/settings.json` as `API_KEY_<PROVIDER>` - plain text, owner-only file permissions where the OS supports it.
     Only used when no usable keyring exists; the Settings screen says so.
  3. environment variables / `.env` (OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, PERPLEXITY_API_KEY, ZAI_API_KEY)
  4. legacy single `LLM_API_KEY` (older versions) - only for the currently selected provider
Keys are never written to logs: `redact()` masks them in every error message and `install_log_redaction()` masks them in
all log records.
"""
from __future__ import annotations

import logging
import os
import re
import threading

SERVICE = "ai-project-mentor"
_lock = threading.Lock()
_cache: dict[str, str] = {}          # provider -> key (memory only; avoids slow keyring lookups on every request)
_KEYRING = None                       # None = not probed yet, False = unusable, otherwise the keyring module
_PATTERNS = [re.compile(p) for p in (
    r"sk-ant-[A-Za-z0-9_\-]{10,}", r"sk-proj-[A-Za-z0-9_\-]{10,}", r"sk-[A-Za-z0-9_\-]{16,}", r"AIza[0-9A-Za-z_\-]{20,}",
    r"pplx-[A-Za-z0-9]{16,}", r"(?i)bearer\s+[A-Za-z0-9._\-]{12,}")]


def _provider_env_names(provider: str) -> list[str]:
    from config import PROVIDER_INFO
    return list(PROVIDER_INFO.get(provider, {}).get("env", []))


def _keyring():
    """The keyring module if a real backend exists, else False."""
    global _KEYRING
    if _KEYRING is None:
        try:
            import keyring
            backend = keyring.get_keyring()
            _KEYRING = False if backend.__class__.__module__.startswith("keyring.backends.fail") else keyring
        except Exception:   # not installed, or the platform has no backend
            _KEYRING = False
    return _KEYRING


def reset_probe() -> None:
    """For tests: forget the cached keyring decision and all cached keys."""
    global _KEYRING
    _KEYRING = None
    _cache.clear()


def backend_description() -> str:
    kr = _keyring()
    if kr:
        name = kr.get_keyring().__class__.__name__
        nice = {"WinVaultKeyring": "Windows Credential Manager", "Keyring": "OS keyring", "Keychain": "macOS Keychain"}
        return nice.get(name, f"OS keyring ({name})")
    return "storage/settings.json (plain text; install the optional 'keyring' package for secure storage)"


def is_secure_backend() -> bool:
    return bool(_keyring())


def _settings():
    from config import settings
    return settings


def _user(provider: str) -> str:
    return f"{provider}_api_key"


def get_key(provider: str) -> str:
    """The key for `provider` ('' when none is configured)."""
    with _lock:
        if provider in _cache:
            return _cache[provider]
    key = ""
    kr = _keyring()
    if kr:
        try:
            key = kr.get_password(SERVICE, _user(provider)) or ""
        except Exception:
            key = ""
    s = _settings()
    if not key:
        key = s._overrides.get(f"API_KEY_{provider.upper()}", "")
    if not key:
        for name in _provider_env_names(provider):
            if os.environ.get(name):
                key = os.environ[name]
                break
    if not key and s.get("LLM_PROVIDER") == provider:
        key = s.get("LLM_API_KEY")            # legacy single-key setting
    key = key.strip()
    with _lock:
        _cache[provider] = key
    return key


def has_key(provider: str) -> bool:
    return bool(get_key(provider))


def set_key(provider: str, key: str) -> str:
    """Store a key; returns a description of where it was stored."""
    key = key.strip()
    if not key:
        raise ValueError("empty API key")
    s = _settings()
    kr = _keyring()
    where = backend_description()
    if kr:
        try:
            kr.set_password(SERVICE, _user(provider), key)
            s.remove([f"API_KEY_{provider.upper()}"])     # never keep a plain-text copy next to the secure one
        except Exception:
            kr = False
    if not kr:
        s.update({f"API_KEY_{provider.upper()}": key})
        where = "storage/settings.json (plain text)"
    with _lock:
        _cache[provider] = key
    return where


def delete_key(provider: str) -> None:
    kr = _keyring()
    if kr:
        try:
            kr.delete_password(SERVICE, _user(provider))
        except Exception:
            pass
    _settings().remove([f"API_KEY_{provider.upper()}"])
    with _lock:
        _cache.pop(provider, None)
    if _settings().get("LLM_PROVIDER") == provider and _settings().get("LLM_API_KEY"):
        _settings().remove(["LLM_API_KEY"])
        with _lock:
            _cache[provider] = ""


def migrate_legacy() -> bool:
    """Move an old plain-text `LLM_API_KEY` from settings.json into the secure store (only if a real keyring exists)."""
    s = _settings()
    legacy = s._overrides.get("LLM_API_KEY", "").strip()
    provider = s.get("LLM_PROVIDER")
    if not legacy or not _keyring() or not provider:
        return False
    if not _keyring().get_password(SERVICE, _user(provider)):
        set_key(provider, legacy)
    s.remove(["LLM_API_KEY"])
    with _lock:
        _cache.pop(provider, None)
    return True


def mask(key: str) -> str:
    return "" if not key else ("*" * 6 + key[-4:] if len(key) > 8 else "*" * len(key))


def redact(text: str) -> str:
    """Mask every known key and every key-looking token in `text`."""
    if not text:
        return text
    with _lock:
        known = [k for k in _cache.values() if len(k) >= 8]
    for k in known:
        text = text.replace(k, "***")
    for p in _PATTERNS:
        text = p.sub("***", text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(record.getMessage())
            record.args = ()
        except Exception:
            pass
        return True


def install_log_redaction() -> None:
    root = logging.getLogger()
    if not any(isinstance(f, RedactingFilter) for f in root.filters):
        root.addFilter(RedactingFilter())
    for h in root.handlers:                      # filters on the root logger do not cover child loggers' records
        if not any(isinstance(f, RedactingFilter) for f in h.filters):
            h.addFilter(RedactingFilter())
