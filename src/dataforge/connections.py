"""Session credentials and explicit process-environment credential entry."""
from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

DEFAULT_KEY_ENV = {
    name: 'DATAFORGE_' + suffix for name, suffix in {
        'OpenAI': 'OPENAI_API_KEY', 'Anthropic': 'ANTHROPIC_API_KEY',
        'Ollama': 'OLLAMA_API_KEY', 'LM Studio': 'LM_STUDIO_API_KEY',
        'OmniRoute': 'OMNIROUTE_API_KEY', 'Databricks': 'DATABRICKS_TOKEN',
        'Azure OpenAI': 'AZURE_OPENAI_API_KEY', 'Gemini': 'GEMINI_API_KEY',
        'OpenRouter': 'OPENROUTER_API_KEY', 'OpenAI compatible': 'CUSTOM_API_KEY',
    }.items()
}


def _validate_credential(name: str, secret: str) -> None:
    """Validate an application-prefixed credential name and bounded single-line value."""
    if not re.fullmatch(r'DATAFORGE_[A-Z][A-Z0-9_]*', name):
        raise ValueError('Runtime credential names must start with DATAFORGE_')
    if not secret or len(secret) > 16384 or any(char in secret for char in '\n\r\0'):
        raise ValueError('Enter a nonempty, single-line runtime credential without null characters')


def set_credential_environment(name: str, secret: str) -> None:
    """Set only this process's environment; never write files or session credentials."""
    _validate_credential(name, secret)
    os.environ[name] = secret


class RuntimeConnections:
    """Manage process-local credentials and redact their values from text and records."""

    def __init__(self) -> None:
        """Initialize empty registered-credential and redaction state."""
        self._credentials: dict[str, tuple[str, float | None]] = {}
        self._resolved: set[str] = set()

    def register(self, name: str, secret: str, ttl: float | None = None) -> None:
        """Register a credential, optionally expiring it after the given number of seconds."""
        _validate_credential(name, secret)
        self._credentials[name] = (secret, None if ttl is None else time.monotonic() + ttl)

    def registered(self, name: str) -> bool:
        """Check whether a named credential is currently registered and unexpired."""
        value = self._credentials.get(name)
        return bool(value and (value[1] is None or value[1] > time.monotonic()))

    def resolve(self, name: str) -> str:
        """Resolve a registered credential or read its value from the process environment."""
        credential = self._credentials.get(name)
        if credential:
            secret, expires = credential
            if expires is None or expires > time.monotonic():
                return secret
            self._credentials.pop(name, None)
        # Remember names for redaction, never copy environment secrets into session state.
        value = os.environ.get(name, '') if name else ''
        if value:
            self._resolved.add(name)
        return value

    def clear(self, name: str | None = None) -> None:
        """Clear one registered credential or all credentials and redaction names."""
        if name is None:
            self._credentials.clear()
            self._resolved.clear()
        else:
            self._credentials.pop(name, None)
            self._resolved.discard(name)

    def scoped_environment(self, names: list[str]) -> dict[str, str]:
        """Return only requested application-prefixed credentials that resolve to values."""
        if any(not re.fullmatch(r'DATAFORGE_[A-Z][A-Z0-9_]*', name) for name in names):
            raise ValueError('Only application-prefixed variables may be injected')
        return {name: value for name in names if (value := self.resolve(name))}

    def redaction_values(self, request_secrets: tuple[str, ...] = ()) -> set[str]:
        """Runtime-only secret values; used to withhold split streaming credentials."""
        secrets = [*request_secrets, *(value[0] for value in self._credentials.values())]
        secrets.extend(os.environ[name] for name in self._resolved if os.environ.get(name))
        secrets.extend(value for name, value in os.environ.items()
                       if re.search(r'(?:KEY|TOKEN|PASSWORD|SECRET)$', name, re.I) and value)
        return {variant for secret in secrets if secret for variant in
            (secret, json.dumps(secret)[1:-1], json.dumps(secret, ensure_ascii=False)[1:-1])}

    def redact(self, text: str, request_secrets: tuple[str, ...] = ()) -> str:
        """Redact registered, request, environment, and credential-shaped secret values."""
        for secret in sorted(self.redaction_values(request_secrets), key=len, reverse=True):
            variants = {secret, json.dumps(secret)[1:-1], json.dumps(secret, ensure_ascii=False)[1:-1]}
            for variant in sorted(variants, key=len, reverse=True):
                text = text.replace(variant, '[REDACTED]')
        text = re.sub(r'(?i)(Bearer\s+)[^\s"\'<>]+', r'\1[REDACTED]', text)
        return re.sub(r"(?i)(\b(?:password|api[_-]?key|token|secret)\s*[=:]\s*)(['\"]?)[^\s;'\"]+\2",
                      r"\1'[REDACTED]'", text)

    def sanitize(self, value: Any, request_secrets: tuple[str, ...] = ()) -> Any:
        """Redact a copy of a JSON-like tree and reject cyclic or overly deep containers."""
        ancestors: set[int] = set()

        def visit(item: Any, depth: int) -> Any:
            """Recursively sanitize strings and containers while tracking active ancestors."""
            if isinstance(item, str):
                return self.redact(item, request_secrets)
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
                    return {self.redact(k, request_secrets): visit(v, depth + 1) for k, v in item.items()}
                return [visit(child, depth + 1) for child in item]
            finally:
                ancestors.remove(identity)

        return visit(value, 0)


_active: ContextVar[RuntimeConnections | None] = ContextVar('dataforge_connections', default=None)


def current_connections() -> RuntimeConnections:
    """Return the active context's credential manager or a fresh empty manager."""
    return _active.get() or RuntimeConnections()


@contextmanager
def connection_scope(manager: RuntimeConnections) -> Iterator[RuntimeConnections]:
    """Make a credential manager current for this context and restore the prior manager."""
    token = _active.set(manager)
    try:
        yield manager
    finally:
        _active.reset(token)
