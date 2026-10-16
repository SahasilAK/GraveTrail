"""Runtime-only credentials. Scope a manager per session; never mutate os.environ."""
from __future__ import annotations

import os
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar

DEFAULT_KEY_ENV = {
    name: 'DATAFORGE_' + suffix for name, suffix in {
        'OpenAI': 'OPENAI_API_KEY', 'Anthropic': 'ANTHROPIC_API_KEY',
        'Ollama': 'OLLAMA_API_KEY', 'LM Studio': 'LM_STUDIO_API_KEY',
        'OmniRoute': 'OMNIROUTE_API_KEY', 'Databricks': 'DATABRICKS_TOKEN',
        'Azure OpenAI': 'AZURE_OPENAI_API_KEY', 'Gemini': 'GEMINI_API_KEY',
        'OpenRouter': 'OPENROUTER_API_KEY', 'OpenAI compatible': 'CUSTOM_API_KEY',
    }.items()
}


class RuntimeConnections:
    def __init__(self):
        self._credentials: dict[str, tuple[str, float | None]] = {}

    def register(self, name: str, secret: str, ttl: float | None = None):
        if not re.fullmatch(r'DATAFORGE_[A-Z][A-Z0-9_]*', name):
            raise ValueError('Runtime credential names must start with DATAFORGE_')
        if not secret or len(secret) > 16384 or '\n' in secret or '\r' in secret:
            raise ValueError('Enter a nonempty, single-line runtime credential')
        self._credentials[name] = (secret, None if ttl is None else time.monotonic() + ttl)

    def resolve(self, name: str) -> str:
        credential = self._credentials.get(name)
        if credential:
            secret, expires = credential
            if expires is None or expires > time.monotonic():
                return secret
            self._credentials.pop(name, None)
        # Explicit legacy environment references remain read-only for compatibility.
        return os.environ.get(name, '') if name else ''

    def clear(self, name: str | None = None):
        if name is None:
            self._credentials.clear()
        else:
            self._credentials.pop(name, None)

    def scoped_environment(self, names: list[str]) -> dict[str, str]:
        if any(not re.fullmatch(r'DATAFORGE_[A-Z][A-Z0-9_]*', name) for name in names):
            raise ValueError('Only application-prefixed variables may be injected')
        return {name: value for name in names if (value := self.resolve(name))}

    def redact(self, text: str) -> str:
        secrets = [value[0] for value in self._credentials.values()]
        secrets.extend(value for name, value in os.environ.items()
                       if re.search(r'(?:KEY|TOKEN|PASSWORD|SECRET)$', name, re.I) and value)
        for secret in sorted(set(secrets), key=len, reverse=True):
            text = text.replace(secret, '[REDACTED]')
        text = re.sub(r'(?i)(Bearer\s+)[^\s"\'<>]+', r'\1[REDACTED]', text)
        return re.sub(r"(?i)(\b(?:password|api[_-]?key|token|secret)\s*[=:]\s*)(['\"]?)[^\s;'\"]+\2",
                      r"\1'[REDACTED]'", text)


_active: ContextVar[RuntimeConnections | None] = ContextVar('dataforge_connections', default=None)


def current_connections() -> RuntimeConnections:
    return _active.get() or RuntimeConnections()


@contextmanager
def connection_scope(manager: RuntimeConnections):
    token = _active.set(manager)
    try:
        yield manager
    finally:
        _active.reset(token)
