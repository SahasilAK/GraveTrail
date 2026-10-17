"""Runtime-only credentials. Scope a manager per session; never mutate os.environ."""
from __future__ import annotations

import json
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
        self._resolved: dict[str, str] = {}

    def register(self, name: str, secret: str, ttl: float | None = None):
        if not re.fullmatch(r'DATAFORGE_[A-Z][A-Z0-9_]*', name):
            raise ValueError('Runtime credential names must start with DATAFORGE_')
        if not secret or len(secret) > 16384 or '\n' in secret or '\r' in secret:
            raise ValueError('Enter a nonempty, single-line runtime credential')
        self._credentials[name] = (secret, None if ttl is None else time.monotonic() + ttl)

    def registered(self, name: str) -> bool:
        value = self._credentials.get(name)
        return bool(value and (value[1] is None or value[1] > time.monotonic()))

    def resolve(self, name: str) -> str:
        credential = self._credentials.get(name)
        if credential:
            secret, expires = credential
            if expires is None or expires > time.monotonic():
                self._resolved[name] = secret
                return secret
            self._credentials.pop(name, None)
        # Explicit legacy environment references remain read-only for compatibility.
        value = os.environ.get(name, '') if name else ''
        if value:
            self._resolved[name] = value
        return value

    def clear(self, name: str | None = None):
        if name is None:
            self._credentials.clear()
            self._resolved.clear()
        else:
            self._credentials.pop(name, None)
            self._resolved.pop(name, None)

    def scoped_environment(self, names: list[str]) -> dict[str, str]:
        if any(not re.fullmatch(r'DATAFORGE_[A-Z][A-Z0-9_]*', name) for name in names):
            raise ValueError('Only application-prefixed variables may be injected')
        return {name: value for name in names if (value := self.resolve(name))}

    def redact(self, text: str) -> str:
        secrets = [value[0] for value in self._credentials.values()]
        secrets.extend(self._resolved.values())
        secrets.extend(value for name, value in os.environ.items()
                       if re.search(r'(?:KEY|TOKEN|PASSWORD|SECRET)$', name, re.I) and value)
        for secret in sorted(set(secrets), key=len, reverse=True):
            variants = {secret, json.dumps(secret)[1:-1], json.dumps(secret, ensure_ascii=False)[1:-1]}
            for variant in sorted(variants, key=len, reverse=True):
                text = text.replace(variant, '[REDACTED]')
        text = re.sub(r'(?i)(Bearer\s+)[^\s"\'<>]+', r'\1[REDACTED]', text)
        return re.sub(r"(?i)(\b(?:password|api[_-]?key|token|secret)\s*[=:]\s*)(['\"]?)[^\s;'\"]+\2",
                      r"\1'[REDACTED]'", text)

    def sanitize(self, value):
        """Redact copies of dict/list trees; reject cycles or more than 64 containers deep."""
        ancestors: set[int] = set()

        def visit(item, depth):
            if isinstance(item, str):
                return self.redact(item)
            if not isinstance(item, (dict, list)):
                return item
            if depth >= 64:
                raise ValueError('Sanitization exceeds nesting limit')
            identity = id(item)
            if identity in ancestors:
                raise ValueError('Sanitization requires acyclic containers')
            ancestors.add(identity)
            try:
                if isinstance(item, dict):
                    return {self.redact(k): visit(v, depth + 1) for k, v in item.items()}
                return [visit(child, depth + 1) for child in item]
            finally:
                ancestors.remove(identity)

        return visit(value, 0)


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
