"""Provider-specific HTTP adapters and strictly grounded, privacy-gated assistance."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import time
import uuid
from contextlib import ExitStack
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Literal, Self
from urllib.parse import quote, urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dataforge.ai_analysis_models import (
    AnalysisUnit,
    LineageReviewResponse,
    NormalizedFact,
    ProjectLineageResponse,
    UnitAttemptResult,
)
from dataforge.ai_budget import project_profile, request_allowance
from dataforge.ai_results import TASK_SCHEMAS, validate_advisory
from dataforge.ai_wire import SourceCitationError
from dataforge.asset_identity import source_job, unambiguous_job_assets
from dataforge.configuration import LLMResourceSettings, ParsingSettings
from dataforge.connections import connection_scope, current_connections
from dataforge.llm_resources import request_slot
from dataforge.model_capabilities import (
    ModelCapabilities,
    ModelDescriptor,
    bind_capabilities,
    capability_identity,
    execution_profile,
    merge_descriptors,
    normalize_model,
)
from dataforge.models import canonical, stable_id, statements
from dataforge.parsers.sas import parse_sas, strip_comments

if TYPE_CHECKING:
    from dataforge.store import Store

PROVIDERS = {"OpenAI": "https://api.openai.com/v1", "Anthropic": "https://api.anthropic.com/v1",
    "Ollama": "http://localhost:11434", "LM Studio": "http://localhost:1234/v1",
    "OmniRoute": "http://localhost:20128/v1", "OpenAI compatible": "http://localhost:8000/v1",
    "Databricks": "https://your-workspace.cloud.databricks.com", "Azure OpenAI": "https://your-resource.openai.azure.com",
    "Gemini": "https://generativelanguage.googleapis.com/v1beta", "OpenRouter": "https://openrouter.ai/api/v1"}
MANUAL_TASKS = ["sas_lineage", "sql_lineage", "lineage_validation", "column_usage", "code_explanation"]
PROJECT_TASKS = ["project_lineage", "lineage_review"]
ROUTABLE_TASKS = MANUAL_TASKS + PROJECT_TASKS
TASKS = MANUAL_TASKS  # Existing manual selectors must keep their five contracts.
PROJECT_SCHEMAS = {"project_lineage": ProjectLineageResponse, "lineage_review": LineageReviewResponse}
PROJECT_PROTOCOLS = {'project_lineage': ('4', '6'), 'lineage_review': ('2', '4')}
PROMPTS = Path(__file__).resolve().parents[2] / "prompts"
if not PROMPTS.is_dir():
    PROMPTS = Path(__file__).resolve().parent / "prompts"


def is_local(url: str) -> bool:
    """Check whether a provider URL points to a loopback host.

    Args:
        url: Provider base URL to inspect.

    Returns:
        Whether the URL host is localhost or a loopback IP address."""
    host = urlparse(url).hostname
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    base_url: str
    model: str = Field(min_length=1, max_length=250)
    name: str = "Default"
    key_env: str = ""
    auth: Literal["auto", "none", "bearer", "api-key", "x-api-key", "x-goog-api-key"] = "auto"
    timeout: float = Field(default=30, ge=1, le=3600)
    retries: int = Field(default=1, ge=0, le=2)
    max_tokens: int = Field(default=2048, ge=64, le=32000)
    context_chars: int = Field(default=16000, ge=500, le=200000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    structured: bool = True
    quota_group: str = Field(default='', max_length=100, pattern=r'^[A-Za-z0-9_.-]*$')
    api_version: str = "2024-10-21"
    model_capabilities: ModelCapabilities | None = None
    context_mode: Literal['automatic', 'custom'] = 'custom'
    output_mode: Literal['automatic', 'custom'] = 'custom'
    source_limit_policy: Literal['unconfirmed', 'token_capacity', 'explicit'] = 'unconfirmed'
    source_disclosure_chars: int | None = Field(default=None, ge=1)

    @model_validator(mode='after')
    def bound_capabilities(self) -> Self:
        """Discard capability metadata that no longer matches this profile."""
        if self.model_capabilities and self.model_capabilities.identity != capability_identity(self):
            self.model_capabilities = None
        return self

    @field_validator("provider")
    @classmethod
    def provider_known(cls, value: str) -> str:
        """Reject provider names that are not supported.

        Args:
            value: Provider name supplied to the profile.

        Returns:
            The validated provider name.

        Raises:
            ValueError: If the provider name is unsupported."""
        if value not in PROVIDERS:
            raise ValueError("Unsupported provider")
        return value

    @field_validator("base_url")
    @classmethod
    def secure_endpoint(cls, value: str) -> str:
        """Validate endpoint transport and remove its trailing slash.

        Args:
            value: HTTP(S) provider base URL.

        Returns:
            The validated base URL without a trailing slash.

        Raises:
            ValueError: If the URL is malformed, contains credentials or URL parameters, or uses remote HTTP."""
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Use an HTTP(S) base URL without credentials, query or fragment")
        if parsed.scheme != "https" and not is_local(value):
            raise ValueError("Remote endpoints require HTTPS")
        return value.rstrip("/")

    @field_validator("key_env")
    @classmethod
    def env_name(cls, value: str) -> str:
        """Validate a credential environment variable name.

        Args:
            value: Environment variable reference to validate.

        Returns:
            The validated variable name.

        Raises:
            ValueError: If the value is not a valid environment variable name."""
        if value and not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", value):
            raise ValueError("Enter an environment variable name, never the secret value")
        return value


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(min_length=1, max_length=500)
    target: str = Field(min_length=1, max_length=500)
    operation: str = Field(min_length=1, max_length=50)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=10000)
    explanation: str = Field(max_length=5000)
    confidence: float = Field(ge=0, le=1)


class GroundedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[Claim] = Field(default_factory=list, max_length=100)
    explanation: str = Field(default="", max_length=20000)
    unresolved_symbols: list[str] = Field(default_factory=list, max_length=100)


class ProviderError(Exception):
    """Describe a provider failure and whether retrying may succeed."""

    def __init__(self, message: str, retryable: bool=False, *, unknown: bool=False) -> None:
        """Create a provider error with its retryability flag.

        Args:
            message: Safe summary of the provider failure.
            retryable: Whether the failed operation may be retried."""
        super().__init__(message)
        self.retryable = retryable
        self.unknown = unknown


def response_object(text: str) -> dict[str, Any]:
    """Parse a JSON object, optionally enclosed in one JSON code fence.

    Args:
        text: Provider response text to parse.

    Returns:
        The decoded JSON object.

    Raises:
        ValueError: If the content is not a JSON object or exceeds JSON nesting limits."""
    if not isinstance(text, str):
        raise ValueError("Provider content must be a JSON object")
    text = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced[1]
    try:
        obj = json.loads(text)
    except RecursionError:
        raise ValueError("Provider JSON exceeds nesting limits") from None
    if not isinstance(obj, dict):
        raise ValueError("Provider content must be a JSON object")
    return obj


class Adapter:
    """Send non-streaming requests to a configured model provider."""

    def __init__(self, profile: Profile, transport: httpx.BaseTransport | None=None, cancelled: Callable[[], bool] | None=None, before_attempt: Callable[[Profile], float] | None=None, check: Callable[[], None] | None=None, response_observer=None, wait=None, retry_unknown_transports=True) -> None:
        """Create an HTTP client for the profile and current cancellation source.

        Args:
            profile: Validated provider configuration.
            transport: Optional HTTPX transport used for the request.
            cancelled: Optional callback that reports request cancellation.
            before_attempt: Optional callback that authorizes an attempt and returns its timeout.
            check: Optional callback that raises when the request is no longer authorized."""
        self.profile = profile
        self.connections = current_connections()
        self.cancelled = cancelled
        self.before_attempt = before_attempt
        self.check = check
        self.completion_metadata = {}
        self.response_observer = response_observer
        self.wait = wait or self._wait
        self.retry_unknown_transports = retry_unknown_transports
        self.client = httpx.Client(timeout=profile.timeout, follow_redirects=False, trust_env=False, transport=transport)

    def __enter__(self) -> Adapter:
        """Return this adapter for use as a context manager."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Close the underlying HTTP client when leaving a context.

        Args:
            args: Exception information supplied by the context manager protocol."""
        self.client.close()

    def _headers(self) -> dict[str, str]:
        """Build request headers using the configured credential reference.

        Returns:
            Headers for the provider request, including configured authentication.

        Raises:
            ValueError: If the supplied value violates the operation constraints."""
        p = self.profile
        key = self.connections.resolve(p.key_env)
        if p.key_env and not key:
            raise ValueError(f"Credential environment variable {p.key_env} is not set")
        auth = p.auth
        if auth == "auto":
            auth = {"Anthropic": "x-api-key", "Gemini": "x-goog-api-key", "Azure OpenAI": "api-key"}.get(p.provider, "bearer")
        headers = {"Content-Type": "application/json"}
        if key and auth != "none":
            headers["Authorization" if auth == "bearer" else auth] = "Bearer " + key if auth == "bearer" else key
        if p.provider == "Anthropic":
            headers["anthropic-version"] = "2023-06-01"
        return headers

    def _request(self, method: str, path: str, payload: dict[str, Any] | None=None) -> dict[str, Any]:
        """Send one bounded JSON request and sanitize its response.

        Args:
            method: HTTP method for the provider endpoint.
            path: Provider-relative request path.
            payload: JSON request body, when the method requires one.

        Returns:
            Sanitized provider response object.

        Raises:
            ProviderError: If the request fails, is cancelled, or returns invalid or oversized content."""
        for attempt in range(self.profile.retries + 1):
            if self.cancelled and self.cancelled():
                raise ProviderError("AI request cancelled; no further retries")
            try:
                timeout = self.before_attempt(self.profile) if self.before_attempt else self.profile.timeout
                if self.check:
                    self.check()
                # Admission can wait: resolve credentials only at the disclosure boundary.
                headers = self._headers()
                request_secrets = tuple(value.removeprefix('Bearer ') for name, value in headers.items()
                    if name.lower() in {'authorization', 'api-key', 'x-api-key', 'x-goog-api-key'})
                with self.client.stream(method, self.profile.base_url + path, headers=headers, json=payload,
                                        timeout=timeout or self.profile.timeout) as response:
                    if self.response_observer:
                        from dataforge.ai_rate_limits import normalize_rate_limits
                        self.response_observer(response.status_code,
                            normalize_rate_limits(self.profile.provider, dict(response.headers), now=time.time()))
                    category = ''
                    if response.status_code == 429:
                        chunks, total = [], 0
                        for chunk in response.iter_bytes():
                            total += len(chunk)
                            if total > 65536:
                                break
                            chunks.append(chunk)
                        try:
                            error = json.loads(b''.join(chunks)).get('error', {})
                            code = error.get('code', '') if isinstance(error, dict) else ''
                            if code in {'insufficient_quota', 'credit_balance_too_low', 'billing_hard_limit_reached'}:
                                category = 'provider_credits_exhausted'
                            elif code in {'daily_quota_exceeded', 'daily_limit_exceeded'}:
                                category = 'provider_daily_quota_exhausted'
                            elif isinstance(error, dict) and any('perday' in str(item).lower() for item in error.get('details', [])):
                                category = 'provider_daily_quota_exhausted'
                        except (ValueError, TypeError, AttributeError):
                            pass
                    if category:
                        raise ProviderError(category)
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt < self.profile.retries:
                            from dataforge.ai_rate_limits import retry_delay
                            self.wait(retry_delay(attempt, dict(response.headers), now=time.time()))
                            continue
                    if response.status_code >= 300:
                        raise ProviderError(f"Provider request failed (HTTP {response.status_code})",
                                            response.status_code == 429 or response.status_code >= 500)
                    chunks, total = [], 0
                    for chunk in response.iter_bytes():
                        if self.check:
                            self.check()
                        if self.cancelled and self.cancelled():
                            raise ProviderError("AI request cancelled while receiving response")
                        total += len(chunk)
                        if total > 2 * 1024 * 1024:
                            raise ProviderError("Provider response exceeds 2 MB limit")
                        chunks.append(chunk)
                    try:
                        data = json.loads(b"".join(chunks))
                        if not isinstance(data, dict):
                            raise ProviderError("Provider response must be a JSON object")
                        return self.connections.sanitize(data, request_secrets)
                    except (ValueError, UnicodeError, RecursionError):
                        raise ProviderError("Provider returned invalid JSON") from None
            except httpx.TransportError:
                if not self.retry_unknown_transports:
                    raise ProviderError('Provider response outcome is unknown', unknown=True) from None
                if attempt >= self.profile.retries:
                    raise ProviderError("Provider connection failed or timed out", True) from None
                self.wait(min(60, 2 ** attempt))
        raise ProviderError("Provider request failed")

    def _wait(self, seconds):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            if self.check:
                self.check()
            if self.cancelled and self.cancelled():
                raise ProviderError('AI request cancelled; no further retries')
            time.sleep(min(.2, max(0, until - time.monotonic())))

    def complete(self, system: str, user: str) -> tuple[str, dict]:
        """Submit a system and user prompt using the provider's chat protocol.

        Args:
            system: System instruction text.
            user: User prompt text.

        Returns:
            Provider response text and usage metadata.

        Raises:
            ProviderError: If the provider response has an unsupported shape."""
        p = self.profile
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if p.provider == "Anthropic":
            path = "/messages"
            payload = {"model": p.model, "system": system, "messages": messages[1:], "max_tokens": p.max_tokens}
        elif p.provider == "Ollama":
            path = "/api/chat"
            payload = {"model": p.model, "messages": messages, "stream": False, "options": {"num_predict": p.max_tokens}}
            if p.structured:
                payload["format"] = "json"
            if p.temperature is not None:
                payload["options"]["temperature"] = p.temperature
        elif p.provider == "Gemini":
            path = "/models/" + quote(p.model.removeprefix("models/"), safe="-._") + ":generateContent"
            payload = {"systemInstruction": {"parts": [{"text": system}]},
                       "contents": [{"role": "user", "parts": [{"text": user}]}],
                       "generationConfig": {"maxOutputTokens": p.max_tokens}}
            if p.structured:
                payload["generationConfig"]["responseMimeType"] = "application/json"
            if p.temperature is not None:
                payload["generationConfig"]["temperature"] = p.temperature
        else:
            path = "/chat/completions"
            payload = {"model": p.model, "messages": messages,
                       "max_completion_tokens" if p.provider == "OpenAI" else "max_tokens": p.max_tokens,
                       "stream": False}
            if p.provider == "Databricks":
                path = "/serving-endpoints/" + quote(p.model, safe="-._") + "/invocations"
                payload.pop("model")
            elif p.provider == "Azure OpenAI":
                path = "/openai/deployments/" + quote(p.model, safe="-._") + "/chat/completions?api-version=" + quote(p.api_version, safe="-")
                payload.pop("model")
            if p.structured and p.provider != "Databricks":
                payload["response_format"] = {"type": "json_object"}
        if p.temperature is not None and p.provider not in {"Gemini", "Ollama"}:
            payload["temperature"] = p.temperature
        data = self._request("POST", path, payload)
        finish = None
        envelope_key = 'candidates' if p.provider == 'Gemini' else 'choices'
        if p.provider not in {'Anthropic','Ollama'}:
            choices = data.get(envelope_key)
            if not isinstance(choices,list) or not choices or not isinstance(choices[0],dict):
                raise ProviderError('Provider returned an unsupported response shape')
        if p.provider == 'Anthropic':
            finish = data.get('stop_reason')
        elif p.provider == 'Ollama':
            finish = data.get('done_reason')
        elif p.provider == 'Gemini':
            finish = (data.get('candidates') or [{}])[0].get('finishReason')
        else:
            finish = (data.get('choices') or [{}])[0].get('finish_reason')
        reported_usage = data.get('usage', data.get('usageMetadata', {}))
        if p.provider == 'Ollama':
            reported_usage = {k:data[k] for k in ['prompt_eval_count','eval_count'] if k in data}
        self.completion_metadata = {'finish_reason':finish,
            'truncated':finish in {'length','max_tokens','MAX_TOKENS','model_length'},
            'usage_known':any(type(v) is int for v in reported_usage.values()) if isinstance(reported_usage,dict) else False,
            'resolved_model':data.get('model'), 'requested_model':p.model}
        try:
            if p.provider == "Anthropic":
                return "".join(c.get("text", "") for c in data["content"]), data.get("usage", {})
            if p.provider == "Ollama":
                return data["message"]["content"], {"input_tokens": data.get("prompt_eval_count"), "output_tokens": data.get("eval_count")}
            if p.provider == "Gemini":
                return "".join(c.get("text", "") for c in data["candidates"][0]["content"]["parts"]), data.get("usageMetadata", {})
            return data["choices"][0]["message"]["content"], data.get("usage", {})
        except (KeyError, IndexError, TypeError, AttributeError):
            raise ProviderError("Provider returned an unsupported response shape") from None

    def models(self) -> list[str]:
        """List model identifiers exposed by providers that support discovery.

        Returns:
            Available model or endpoint identifiers.

        Raises:
            ValueError: If Azure deployment discovery is requested through the model API."""
        return [model.id for model in self.model_catalog()]

    def model_catalog(self) -> list[ModelDescriptor]:
        """List provider model descriptors supported by the configured endpoint.

        Returns:
            Available provider model descriptors.

        Raises:
            ValueError: If discovery is unsupported or the returned catalog is invalid.
        """
        if self.profile.provider == "Azure OpenAI":
            raise ValueError("Enter an Azure deployment name manually; model listing requires a separate management API")
        path = "/api/tags" if self.profile.provider == "Ollama" else "/api/2.0/serving-endpoints" if self.profile.provider == "Databricks" else "/models"
        data = self._request("GET", path)
        items = data.get("models", data.get("data", data.get("endpoints", [])))
        if not isinstance(items, list) or len(items) > 20000:
            raise ValueError('Provider model catalog is invalid or exceeds 20,000 models')
        return merge_descriptors(normalize_model(item, self.profile.provider) for item in items)

    def model_details(self, model: str) -> ModelDescriptor:
        """Inspect metadata for a selected model without loading it or submitting source.

        Args:
            model: Provider model identifier to inspect.

        Returns:
            Sanitized model metadata.

        Raises:
            ValueError: If the selected model is absent from the provider catalog.
        """
        if self.profile.provider == 'Ollama':
            data = self._request('POST', '/api/show', {'model': model})
            descriptor = normalize_model({**data, 'id': model}, 'Ollama')
            # Native trained capacity can exceed the currently loaded allocation.
            try:
                running = self._request('GET', '/api/ps').get('models', [])
            except ProviderError:
                running = []
            allocated = [normalize_model({**item, 'id': model}, 'Ollama') for item in running
                         if isinstance(item, dict) and item.get('name', item.get('model')) == model]
            descriptor = merge_descriptors([descriptor, *allocated])[0]
            if allocated:
                descriptor = descriptor.model_copy(update={'capabilities': descriptor.capabilities.model_copy(update={'source': 'runtime'})})
        else:
            descriptor = next((item for item in self.model_catalog() if item.id == model), None)
            if descriptor is None:
                raise ValueError('Selected model is absent from the provider catalog')
        profile = self.profile.model_copy(update={'model': model})
        return descriptor.model_copy(update={'capabilities': bind_capabilities(descriptor.capabilities, profile)})


def validate_response(response: GroundedResponse, code: str, known: set[str], first: int, last: int) -> GroundedResponse:
    """Ensure provider claims exactly match supplied source and asset evidence.

    Args:
        response: Structured provider response to validate.
        code: Original source text used as evidence.
        known: Asset names allowed in claims.
        first: First source line included in the evidence selection.
        last: Last source line included in the evidence selection.

    Returns:
        The validated response unchanged.

    Raises:
        ValueError: If a claim cites an invalid line range, quote, asset, or read/write relationship."""
    lines = code.splitlines()
    known = {canonical(x) for x in known}
    for claim in response.claims:
        if not first <= claim.start_line <= claim.end_line <= min(last, len(lines)):
            raise ValueError("Claim line range is outside supplied source evidence")
        span = "\n".join(lines[claim.start_line - 1:claim.end_line])
        if claim.quote not in span:
            raise ValueError("Claim quote is not exact source evidence")
        cleaned = re.sub(r"--[^\n]*", "", strip_comments(claim.quote))
        cleaned = re.sub(r"'([^']|'')*'", "''", cleaned)
        cleaned = re.sub(r'["`\[\]]', "", cleaned)
        for name in [claim.source, claim.target]:
            if canonical(name) not in known or not re.search(r"(?<![\w.])" + re.escape(name) + r"(?![\w.])", cleaned, re.I):
                raise ValueError("Claim asset is not known or is absent from code evidence")
        src = re.escape(claim.source)
        tgt = re.escape(claim.target)
        reads = r"(?:from|join|using|set|merge|modify|data\s*=)\s*" + src + r"(?![\w.])"
        writes = r"(?:table|view|into|update|data|out\s*=|base\s*=)\s*" + tgt + r"(?![\w.])"
        same_statement = any(re.search(reads, part, re.I) and re.search(writes, part, re.I)
                             for part, _, _ in statements(cleaned))
        # SAS DATA headers and reads span semicolon-delimited statements; bind them by block.
        same_sas_block = any(canonical(s.name) == canonical(claim.source) and canonical(t.name) == canonical(claim.target)
            for op in parse_sas(claim.quote).operations for s in op.sources for t in op.targets)
        if not same_statement and not same_sas_block:
            raise ValueError("Source and target lack bound read/write evidence in the same statement or SAS block")
    return response


def redact(text: str) -> str:
    """Redact credential values known to the current connection scope.

    Args:
        text: Text that may contain a credential value.

    Returns:
        Text with known credentials replaced by redaction markers."""
    return current_connections().redact(text)


def expire_ai_history(store: Store, workspace: str) -> None:
    """Expire optional request bodies while retaining evidence used by active facts.

    Args:
        store: Workspace store containing AI history.
        workspace: Workspace whose retention policy is applied.
    """
    days = int(store.setting(workspace, 'llm_retention_days', 30))
    referenced = {r['record_id'] for r in store.rows('''SELECT record_id FROM ai_analysis_units WHERE workspace_id=?
        UNION SELECT record_id FROM analysis_fact_support WHERE workspace_id=?''', [workspace, workspace])
        if r['record_id']}
    for record in store.rows("SELECT record_id,outcome,details FROM llm_records WHERE workspace_id=? AND created_at < current_timestamp - ? * INTERVAL '1 day'", [workspace, days]):
        if record['outcome'] == 'merged' or record['record_id'] in referenced:
            minimal = json.loads(record['details'])
            minimal.pop('context', None)
            minimal.pop('response', None)
            store.execute('UPDATE llm_records SET details=? WHERE record_id=?',
                          [json.dumps(minimal), record['record_id']])
        else:
            store.execute('DELETE FROM llm_records WHERE record_id=?', [record['record_id']])


def assist(store: Store, workspace: str, profile: Profile, file_id: str, first: int, last: int, task: str="lineage_validation", profile_id: str="",
           transport: httpx.BaseTransport | None=None, expected_hash: str | None=None, cancelled: Callable[[], bool] | None=None, expected_job: str | None=None) -> dict[str, Any]:
    """Run one privacy-gated AI request while holding workspace request capacity.

    Args:
        store: Workspace store used to read source and persist the result.
        workspace: Workspace identifier owning the source.
        profile: Provider profile selected for this request.
        file_id: Source file identifier.
        first: First selected source line.
        last: Last selected source line.
        task: Supported prompt task name.
        profile_id: Saved provider profile identifier.
        transport: Optional HTTPX transport for the provider request.
        expected_hash: Optional source hash pinned by an earlier preview.
        cancelled: Optional callback that reports request cancellation.
        expected_job: Optional source job identity pinned by an earlier preview.

    Returns:
        A persisted request result, including outcome, usage, and retryability.

    Raises:
        InterruptedError: If the request is cancelled before transmission."""
    if cancelled and cancelled():
        raise InterruptedError('AI request cancelled before transmission')
    resources = LLMResourceSettings.model_validate({k: store.setting(workspace, k, v)
        for k, v in LLMResourceSettings().model_dump().items()})
    with ExitStack() as stack:
        try:
            stack.enter_context(request_slot(store.home, workspace, resources.llm_concurrency))
        except ValueError:
            return {'record_id': '', 'outcome': 'quarantined', 'reason': 'ValueError',
                    'result': None, 'usage': {}, 'retryable': False}
        stack.enter_context(connection_scope(current_connections()))
        return _assist(store, workspace, profile, file_id, first, last, task, profile_id,
                       transport, expected_hash, cancelled, expected_job)


def _assist(store: Store, workspace: str, profile: Profile, file_id: str, first: int, last: int, task: str, profile_id: str, transport: httpx.BaseTransport | None, expected_hash: str | None, cancelled: Callable[[], bool] | None, expected_job: str | None=None) -> dict[str, Any]:
    """Build, send, validate, and persist one bounded AI assistance request.

    Args:
        store: Workspace store used for evidence and persistence.
        workspace: Workspace identifier owning the source.
        profile: Provider profile selected for the request.
        file_id: Source file identifier.
        first: First selected source line.
        last: Last selected source line.
        task: Supported prompt task name.
        profile_id: Saved provider profile identifier.
        transport: Optional HTTPX transport for the provider request.
        expected_hash: Optional source hash pinned by an earlier preview.
        cancelled: Optional callback that reports request cancellation.
        expected_job: Optional source job identity pinned by an earlier preview.

    Returns:
        Persisted result metadata and any validated response.

    Raises:
        InterruptedError: If cancellation is observed before transmission.
        ValueError: If the task, source, selection, privacy policy, or evidence bounds are invalid."""
    if cancelled and cancelled():
        raise InterruptedError("AI request cancelled before transmission")
    if task not in TASKS:
        raise ValueError("Unsupported analysis task")
    if not is_local(profile.base_url) and not store.setting(workspace, "external_llm", False):
        raise ValueError("External LLM requests are disabled in Security and privacy")
    source = store.file(file_id)
    from dataforge.dbt.service import is_dbt
    if is_dbt(source):
        raise ValueError('dbt currently requires parser analysis')
    if source["workspace_id"] != workspace:
        raise ValueError("Source does not belong to this workspace")
    if expected_hash is not None and source["content_hash"] != expected_hash:
        raise ValueError("Source changed; refresh the evidence preview before requesting assistance")
    lines = source["raw_content"].splitlines()
    if not 1 <= first <= last <= len(lines):
        raise ValueError("Select a valid source line range")
    if not is_local(profile.base_url) and first == 1 and last == len(lines) and not store.setting(workspace, "allow_full_source", False):
        raise ValueError("Complete source transmission is disabled; select a statement range or change privacy settings")
    focused = "\n".join(lines[first - 1:last])
    budget = min(store.setting(workspace, "max_context_chars", 8000), profile.context_chars)
    if len(focused) > budget:
        raise ValueError("Selected source exceeds context budget; choose a smaller line range")
    if store.setting(workspace, "redact_secrets", True):
        focused = redact(focused)
    system_path = PROMPTS / task / "system.md"
    system = system_path.read_text(encoding="utf-8")
    template = (PROMPTS / task / "user_template.md").read_text(encoding="utf-8")
    response_model = TASK_SCHEMAS.get(task, GroundedResponse)
    schema = response_model.model_json_schema()
    version = "2" if task in TASK_SCHEMAS else "1"
    prompt_hash = hashlib.sha256((system + template + json.dumps(schema, sort_keys=True)).encode()).hexdigest()
    settings = {k: store.setting(workspace, k, value) for k, value in ParsingSettings().model_dump().items()}
    job = source_job(source, settings)
    if expected_job is not None and job != expected_job:
        raise ValueError("Source job changed; refresh the evidence preview before requesting assistance")
    known = {a["name"] for a in unambiguous_job_assets(store.assets(workspace), job).values()}
    user = template.replace("{{context}}", json.dumps({"file_id": file_id, "path": source["relative_path"],
                "start_line": first, "end_line": last, "known_assets": sorted(known), "source": focused,
                "schema": schema, "job_id": job}))
    if len(system) + len(user) > profile.context_chars:
        raise ValueError("Request exceeds the profile context budget; select fewer lines or increase its limit")
    start = time.perf_counter()
    usage, raw, validated = {}, "", None
    outcome, reason, retryable = "validated", "", False
    try:
        with Adapter(profile, transport, cancelled) as adapter:
            if cancelled and cancelled():
                raise InterruptedError("AI request cancelled before transmission")
            raw, usage = adapter.complete(system, user)
        if cancelled and cancelled():
            raise ProviderError("AI request cancelled after response; result quarantined")
        raw = redact(raw)
        usage = json.loads(redact(json.dumps(usage)))
        validated = response_model.model_validate(response_object(raw))
        if task in TASK_SCHEMAS:
            from dataforge.services import source_dialect
            settings["dialect"] = source_dialect(source, settings)
            validate_advisory(validated, source, known, first, last, settings)
        else:
            validate_response(validated, source["raw_content"], known, first, last)
    except (ValueError, ProviderError) as exc:
        outcome, reason = "quarantined", type(exc).__name__
        retryable = isinstance(exc, ProviderError) and exc.retryable
    details = {"content_hash": source["content_hash"], "reason": reason, "schema_version": version, "job_id": job,
               "result": validated.model_dump() if outcome == "validated" else None}
    if store.setting(workspace, "llm_history", False):
        details.update(context=focused, response=raw)
    details = json.loads(redact(json.dumps(details)))
    usage = json.loads(redact(json.dumps(usage)))
    record_id = uuid.uuid4().hex
    with store.transaction():
        store.execute("INSERT INTO prompt_versions VALUES (?,?,?) ON CONFLICT DO NOTHING", [prompt_hash, task, version])
        store.execute("INSERT INTO llm_records(record_id,workspace_id,profile_id,task,file_id,start_line,prompt_hash,provider,model,outcome,duration,usage,details) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      [record_id, workspace, profile_id, task, file_id, first, prompt_hash, profile.provider,
                       profile.model, outcome, time.perf_counter() - start, json.dumps(usage), json.dumps(details)])
        expire_ai_history(store, workspace)
    return {"record_id": record_id, "outcome": outcome, "reason": reason,
            "result": validated.model_dump() if outcome == "validated" else None, "usage": usage,
            "retryable": retryable}


def merge_claims(store: Store, workspace: str, record_id: str) -> int:
    """Merge validated lineage claims into stored evidence under the workspace lock.

    Args:
        store: Workspace store receiving the lineage claims.
        workspace: Workspace identifier owning the validated result.
        record_id: Validated AI result identifier.

    Returns:
        Number of claims merged.

    Raises:
        ValueError: If the result is unvalidated, stale, unsupported, or no longer evidence-grounded."""
    with store.lock:
        return _merge_claims(store, workspace, record_id)


def _merge_claims(store: Store, workspace: str, record_id: str) -> int:
    """Validate a stored AI result and write its claims as inferred lineage.

    Args:
        store: Workspace store receiving the lineage claims.
        workspace: Workspace identifier owning the validated result.
        record_id: Validated AI result identifier.

    Returns:
        Number of claims merged.

    Raises:
        ValueError: If the result is unvalidated, stale, unsupported, or no longer evidence-grounded."""
    records = store.rows("SELECT * FROM llm_records WHERE workspace_id=? AND record_id=? AND outcome='validated'", [workspace, record_id])
    if not records:
        raise ValueError("Only validated AI records can be merged")
    record = records[0]
    if record["task"] not in {"sas_lineage", "sql_lineage", "lineage_validation"}:
        raise ValueError("Only lineage task records can be merged; advisory results cannot create relationships")
    source = store.file(record["file_id"])
    details = json.loads(record["details"])
    if source["content_hash"] != details["content_hash"]:
        raise ValueError("Source changed; run assistance again before merging")
    response = GroundedResponse.model_validate(details["result"])
    config = {key: store.setting(workspace, key, value) for key, value in ParsingSettings().model_dump().items()}
    job = source_job(source, config)
    if details.get("job_id", "workspace") != job:
        raise ValueError("Source job/session assignment changed; request assistance again before merging")
    assets = {name: asset["asset_id"] for name, asset in unambiguous_job_assets(store.assets(workspace), job).items()}
    validate_response(response, source["raw_content"], set(assets), 1, len(source["raw_content"].splitlines()))
    with store.transaction():
        for i, c in enumerate(response.claims):
            sid = stable_id(record_id, str(i))
            oid = stable_id(sid, "llm")
            src, tgt = assets[canonical(c.source)], assets[canonical(c.target)]
            store.execute("INSERT INTO statements VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING", [sid, workspace, source["file_id"], c.start_line, c.end_line, c.quote, source["content_hash"]])
            store.execute("INSERT INTO operations VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING", [oid, workspace, sid, c.operation, "llm", min(c.confidence, .8), json.dumps([c.explanation])])
            store.db.executemany("INSERT INTO operation_assets VALUES (?,?,?,?)", [[workspace, oid, src, "input"], [workspace, oid, tgt, "output"]])
            store.execute("INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING", [stable_id(oid, src, tgt), workspace, src, tgt, oid, sid, source["file_id"], c.operation, "llm", min(c.confidence, .8), "inferred", "llm:" + record_id])
        store.execute("UPDATE llm_records SET outcome='merged' WHERE record_id=?", [record_id])
    return len(response.claims)


def assist_task(store: Store, workspace: str, file_id: str, first: int, last: int, task: str, transport: httpx.BaseTransport | None=None, expected_hash: str | None=None, cancelled: Callable[[], bool] | None=None, authorize: Callable[[str, Profile], Profile] | None=None, expected_job: str | None=None) -> dict[str, Any]:
    """Select a task profile, apply same-origin fallback, and run assistance.

    Args:
        store: Workspace store used to load routing and request data.
        workspace: Workspace identifier owning the source.
        file_id: Source file identifier.
        first: First selected source line.
        last: Last selected source line.
        task: Supported prompt task name.
        transport: Optional HTTPX transport for provider requests.
        expected_hash: Optional source hash pinned by an earlier preview.
        cancelled: Optional callback that reports request cancellation.
        authorize: Optional callback that authorizes a profile identifier and profile.
        expected_job: Optional source job identity pinned by an earlier preview.

    Returns:
        The selected provider request result.

    Raises:
        ValueError: If routing has no configured profile or no usable profile can complete."""
    profiles = {r["profile_id"]: Profile.model_validate_json(r["config"])
                for r in store.rows("SELECT * FROM llm_profiles WHERE workspace_id=?", [workspace])}
    assignments = store.setting(workspace, "task_models", {})
    chosen = assignments.get(task) or store.setting(workspace, "default_profile", "")
    if chosen not in profiles:
        raise ValueError("Configure a default or task-specific provider profile first")
    first_profile = profiles[chosen]
    ids = [chosen, *store.setting(workspace, "fallback_profiles", [])]
    result = None
    for pid in dict.fromkeys(ids):
        if pid not in profiles:
            continue
        profile = profiles[pid]
        # Fallback never silently changes the recipient host or authentication audience.
        if urlparse(profile.base_url).netloc != urlparse(first_profile.base_url).netloc:
            continue
        if authorize:
            profile = authorize(pid, profile)
        result = assist(store, workspace, profile, file_id, first, last, task, pid, transport,
                        expected_hash=expected_hash, cancelled=cancelled, expected_job=expected_job)
        if not result["retryable"]:
            return result
    return result


def analysis_routes(store: Store, workspace: str, task: str) -> list[tuple[str, Profile]]:
    """Resolve configured fallback profiles that share the selected recipient host.

    Args:
        store: Workspace store containing provider settings.
        workspace: Workspace identifier.
        task: Project analysis task to route.

    Returns:
        Ordered profile identifiers and validated profiles.

    Raises:
        ValueError: If the task is invalid or no default profile is configured.
    """
    if task not in PROJECT_TASKS:
        raise ValueError('Project invocation requires a project task')
    profiles = {r['profile_id']:Profile.model_validate_json(r['config'])
                for r in store.rows('SELECT profile_id,config FROM llm_profiles WHERE workspace_id=?',[workspace])}
    chosen = store.setting(workspace,'task_models',{}).get(task) or store.setting(workspace,'default_profile','')
    if chosen not in profiles:
        raise ValueError('Configure a default or project-task provider profile first')
    first = profiles[chosen]
    routes = [(pid,profiles[pid]) for pid in dict.fromkeys([chosen,*store.setting(workspace,'fallback_profiles',[])])
              if pid in profiles and urlparse(profiles[pid].base_url).netloc == urlparse(first.base_url).netloc]
    return routes


def _transmitted_schema(value: Any) -> Any:
    """Remove display annotations recursively while preserving validation keywords.

    Args:
        value: JSON schema value to sanitize.

    Returns:
        Schema data with display-only annotations removed.
    """
    if isinstance(value,list):
        return [_transmitted_schema(item) for item in value]
    if not isinstance(value,dict):
        return value
    result = {}
    for key,item in value.items():
        if key in {'title','default','description','examples'}:
            continue
        if key in {'const','enum','dependentRequired'}:
            result[key] = item
        elif key in {'properties','$defs','definitions','patternProperties','dependentSchemas','dependencies'}:
            result[key] = {name:_transmitted_schema(schema) for name,schema in item.items()}
        else:
            result[key] = _transmitted_schema(item)
    return result


REVIEW_CONTEXT_CHARS = 2000


def review_batches(facts: list[NormalizedFact], *, unit=None, settings=None) -> list[list[dict[str, Any]]]:
    """Split normalized facts into deterministic pages bounded by review context size.

    Args:
        facts: Normalized facts to serialize for review.

    Returns:
        Ordered groups of serialized facts.
    """
    references = {}
    if unit is not None:
        from dataforge.ai_citations import source_references
        for reference in source_references(unit, settings, partial=True):
            references.setdefault(reference['text'], []).append(reference['reference_id'])
    batches, current = [], []
    for fact in facts:
        candidate = fact.model_dump(exclude={'detail','evidence','unit_id','evidence_key','status','origin'}, exclude_defaults=True)
        if candidate.get('expression') in references:
            candidate['expression_references'] = references[candidate.pop('expression')]
        proposed = [*current,candidate]
        if current and (len(proposed)>100 or len(json.dumps(proposed,ensure_ascii=False,separators=(',',':')))>REVIEW_CONTEXT_CHARS):
            batches.append(current)
            current=[]
        current.append(candidate)
    if current:
        batches.append(current)
    return batches


@lru_cache(maxsize=2)
def _analysis_schema_text(task: str) -> str:
    """Serialize the validation schema sent for a project analysis task.

    Args:
        task: Project analysis task whose wire schema is required.

    Returns:
        Compact JSON for the transmitted schema.
    """
    from dataforge.ai_wire import wire_schema
    return json.dumps(_transmitted_schema(wire_schema(task)), sort_keys=True, separators=(',', ':'))


def analysis_prompt_hash(task: str, *, focused: bool=False, source_kind: str='sql') -> str:
    """Hash the system prompt, focus instructions, and transmitted schema.

    Args:
        task: Project analysis task.
        focused: Whether unit-specific focus instructions are included.

    Returns:
        SHA-256 prompt identity.
    """
    system = (PROMPTS/task/'system.md').read_text(encoding='utf-8')
    template = (PROMPTS/task/'user_template.md').read_text(encoding='utf-8')
    focus_path = PROMPTS/task/'focus.md'
    if focused and focus_path.exists():
        system += '\n' + focus_path.read_text(encoding='utf-8')
    if task == 'project_lineage':
        handler = PROMPTS / task / (source_kind + '.md')
        if handler.exists():
            system += '\n' + handler.read_text(encoding='utf-8')
    return hashlib.sha256((system + template + _analysis_schema_text(task)).encode()).hexdigest()


def analysis_prompt(unit: AnalysisUnit, task: str, execution: Any, *, reserve_review: bool=False) -> tuple[str, str, str]:
    """Build the system prompt, bounded JSON user context, and prompt identity.

    Args:
        unit: Analysis unit whose source and evidence are under review.
        task: Project analysis task.
        execution: Current analysis context and privacy settings.
        reserve_review: Whether to reserve maximum review candidate space.

    Returns:
        System prompt, serialized user prompt, and prompt hash.

    Raises:
        ValueError: If the requested task is not a supported project task.
    """
    if task not in PROJECT_SCHEMAS:
        raise ValueError('Unknown project task')
    system = (PROMPTS/task/'system.md').read_text(encoding='utf-8')
    template = (PROMPTS/task/'user_template.md').read_text(encoding='utf-8')
    schema_text = _analysis_schema_text(task)
    schema = json.loads(schema_text)
    digest = analysis_prompt_hash(task, focused=bool(unit.focus), source_kind=unit.source_kind)
    if unit.focus and (PROMPTS/task/'focus.md').exists():
        system += '\n' + (PROMPTS/task/'focus.md').read_text(encoding='utf-8')
    if task == 'project_lineage':
        handler = PROMPTS / task / (unit.source_kind + '.md')
        if handler.exists():
            system += '\n' + handler.read_text(encoding='utf-8')
    from dataforge.ai_source_views import compact_catalog, context_records
    context = {'unit':unit.model_dump(),'settings':execution.settings,'catalog':compact_catalog(execution.catalog),
               'schema':schema,'schema_version':PROJECT_PROTOCOLS[task][0]}
    if getattr(execution, 'resolution_context', None):
        system += '\n' + (PROMPTS / 'project_resolution' / 'system.md').read_text(encoding='utf-8')
        context['resolution'] = execution.resolution_context
    if task in {'project_lineage', 'lineage_review'}:
        from dataforge.ai_citations import source_references
        context['expression_references'] = [
            {k: v for k, v in reference.items()
             if k not in {'start_offset', 'end_offset', 'text'}}
            for reference in source_references(unit, execution.settings, partial=task == 'lineage_review')]
        if unit.source_focus and task == 'project_lineage':
            context['partial_expression_references'] = [
                {k: v for k, v in reference.items() if k != 'text'}
                for reference in source_references(unit, execution.settings, partial=True) if reference.get('partial')]
    if unit.focus or unit.source_focus:
        from dataforge.ai_semantic import source_view, unit_dialect
        context['unit'].pop('code')
        context['source_segments'] = source_view(unit, unit_dialect(unit, execution.settings))
    if unit.source_focus:
        f = unit.source_focus
        records = context_records(execution.catalog, execution.settings)
        if f.context_end > len(records):
            raise ValueError('Source context index changed')
        context['catalog'] = []
        context['settings'] = {}
        context['context_records'] = records[f.context_start:f.context_end]
        context['partial_source_view'] = True
        system += ('\nThis is a partial original-source/context view, never standalone executable code. '
                   'context_records use JSON Pointer paths into catalog/settings; string slices retain offsets. '
                   'Sibling tasks cover omitted ranges. Return only source-supported facts and mark coverage partial; '
                   'report missing dependencies explicitly. Never infer semantics from an omitted range. '
                   'For an expression spanning views, use partial_expression_references and set derivation.fragment=true. '
                   'Report only dependency inputs visible in this view, preserving their full-expression roles/scope. '
                   'The host combines components only after all original expression ranges are covered and validates '
                   'the complete original derivation; a component is never a complete lineage fact.')
    context['evidence_reference'] = {'unit_id': unit.unit_id}
    if task == 'lineage_review':
        context['candidates'] = 'x' * REVIEW_CONTEXT_CHARS if reserve_review and not execution.review_candidates else execution.review_candidates
    user = template.replace('{{context}}',json.dumps(context,ensure_ascii=False,separators=(',',':')))
    return system,user,digest


def preview_analysis_routes(store: Store, workspace: str, units: list[AnalysisUnit], execution: Any,
                            *, tasks: list[str] | None=None) -> dict[str, Any]:
    """Check routes, full-envelope budgets, credentials, and disclosure permissions offline.

    Args:
        store: Workspace store used to read profiles and privacy settings.
        workspace: Workspace identifier.
        units: Analysis units to include in the capacity preview.
        execution: Current execution context and configured resource limits.
        tasks: Optional ordered task list to preview.

    Returns:
        Route availability, blocked reasons, allowances, and budget totals.
    """
    blocked, routes, excluded, allowances = [], {}, [], []
    tasks = tasks or ['project_lineage'] + (['lineage_review'] if execution.request.additional_ai_review else [])
    for task in tasks:
        try:
            selected = analysis_routes(store, workspace, task)
        except ValueError as exc:
            blocked.append({'task': task, 'reason': str(exc)})
            continue
        routes[task] = []
        for index, (pid, profile) in enumerate(selected):
            configured_profile = profile
            if len(units) == 1:
                profile = project_profile(profile, units[0])
            manager = execution.connections or current_connections()
            if hasattr(manager, 'for_profile'):
                manager = manager.for_profile(pid, configured_profile)
            if profile.key_env and not manager.resolve(profile.key_env):
                blocked.append({'task': task, 'profile_id': pid, 'reason': 'credential_unavailable'})
            if not is_local(profile.base_url) and not store.setting(workspace, 'external_llm', False):
                blocked.append({'task': task, 'profile_id': pid, 'reason': 'external_requests_disabled'})
            if not is_local(profile.base_url) and not store.setting(workspace, 'allow_full_source', False):
                blocked.append({'task': task, 'profile_id': pid, 'reason': 'complete_source_permission_required'})
            incompatible = []
            for unit in units:
                system, user, _ = analysis_prompt(unit, task, execution, reserve_review=task == 'lineage_review')
                allowance = request_allowance(profile, system, user,
                    privacy_chars=store.setting(workspace, 'max_context_chars', 8000),
                    context_chars=execution.request.max_context_chars,
                    reserved_source_chars=min(REVIEW_CONTEXT_CHARS,
                        (execution.request.max_context_chars or min(profile.context_chars,
                         store.setting(workspace, 'max_context_chars', 8000))) // 3)
                        if task == 'lineage_review' and not execution.review_candidates else 0)
                allowances.append({'task': task, 'unit_id': unit.unit_id, 'path': unit.path, 'profile_id': pid, **asdict(allowance)})
                incompatible.extend({'task': task, 'unit_id': unit.unit_id, 'profile_id': pid,
                    'reason': reason, 'required_characters': allowance.required_characters} for reason in allowance.reasons)
            if incompatible and index:
                excluded.extend(incompatible)
                continue
            blocked.extend(incompatible)
            routes[task].append({'profile_id': pid, 'provider': profile.provider, 'model': profile.model,
                'base_url': profile.base_url, 'max_tokens': profile.max_tokens,
                'timeout': profile.timeout, 'attempts_per_unit': profile.retries + 1})
    ceiling = sum(p['attempts_per_unit'] for rr in routes.values() for p in rr) * len(units)
    tokens = sum(p['max_tokens'] * p['attempts_per_unit'] for rr in routes.values() for p in rr) * len(units)
    if ceiling > execution.request.max_provider_attempts:
        blocked.append({'reason': 'worst_case_provider_attempt_budget'})
    if tokens > execution.request.max_output_tokens_total:
        blocked.append({'reason': 'worst_case_output_reservation_budget'})
    return {'routes': routes, 'blocked': blocked, 'excluded_routes': excluded, 'allowances': allowances,
            'valid': not blocked, 'max_provider_attempts': ceiling, 'max_output_tokens_reserved': tokens}


def invoke_analysis_unit(store: Store, workspace: str, unit: AnalysisUnit, task: str,
                         execution: Any) -> UnitAttemptResult | None:
    """Run routed project extraction with each provider attempt reauthorized and reserved.

    Args:
        store: Workspace store for immutable source and result records.
        workspace: Workspace identifier.
        unit: Analysis unit to submit.
        task: Project analysis task.
        execution: Current execution state, permissions, and resource reservations.

    Returns:
        The final recorded attempt result, if a route was available.

    Raises:
        ValueError: If budgets, source identity, settings, or provider output are invalid.
    """
    execution.check()
    schema_version, prompt_version = PROJECT_PROTOCOLS[task]
    routes = analysis_routes(store,workspace,task)
    system,user,prompt_hash = analysis_prompt(unit,task,execution)
    manager = execution.connections or current_connections()
    result = None
    invocation_start = execution.attempts
    for pid,profile in routes:
        configured_profile = profile
        profile = project_profile(profile, unit)
        manager = execution.connections or current_connections()
        if hasattr(manager, 'for_profile'):
            manager = manager.for_profile(pid, configured_profile)
        execution.check()
        allowance = request_allowance(profile, system, user, privacy_chars=store.setting(workspace, 'max_context_chars', 8000),
                                      context_chars=execution.request.max_context_chars)
        if not allowance.valid:
            if pid != routes[0][0]:
                continue
            raise ValueError(', '.join(allowance.reasons))
        started,attempt_start = time.perf_counter(),execution.attempts
        usage,raw,validated,metadata = {},'',None,{}
        outcome,reason,retryable = 'validated','',False

        def before_attempt(active_profile):
            execution.check()
            source = store.file(unit.file_id)
            settings = {k:store.setting(workspace,k,v) for k,v in ParsingSettings().model_dump().items()}
            if source['workspace_id'] != workspace or source['content_hash'] != unit.content_hash or source_job(source,settings) != unit.job_id:
                raise ValueError('Source identity changed before provider attempt')
            if source['raw_content'][unit.start_offset:unit.end_offset] != unit.code:
                raise ValueError('Unit code differs from the immutable original')
            current_routes = dict(analysis_routes(store,workspace,task))
            if pid not in current_routes or execution_profile(project_profile(current_routes[pid], unit)) != execution_profile(active_profile):
                raise ValueError('Provider route changed before provider attempt')
            if execution.settings and any(execution.settings.get(k) != v for k,v in settings.items()):
                raise ValueError('Analysis settings changed before provider attempt')
            for fid,digest in execution.source_hashes.items():
                context_source = store.file(fid)
                if context_source['workspace_id'] != workspace or context_source['content_hash'] != digest:
                    raise ValueError('Declaration context changed before provider attempt')
            if not is_local(active_profile.base_url):
                if not store.setting(workspace,'external_llm',False):
                    raise ValueError('External LLM requests are disabled')
                if not store.setting(workspace,'allow_full_source',False):
                    raise ValueError('Complete source transmission is disabled')
            from dataforge.ai_rate_limits import QUOTAS, quota_scope
            wait_until = QUOTAS.admit(quota_scope(active_profile), estimated_input=allowance.estimated_input,
                reserved_output=active_profile.max_tokens, now=time.time())
            if wait_until > time.time():
                execution.wait_provider(wait_until - time.time())
            return execution.before_attempt(active_profile)

        try:
            resources = LLMResourceSettings.model_validate({k:store.setting(workspace,k,v)
                for k,v in LLMResourceSettings().model_dump().items()})
            with connection_scope(manager), request_slot(store.home,workspace,resources.llm_concurrency), Adapter(
                    profile,execution.transport,cancelled=execution.cancelled,before_attempt=before_attempt,check=execution.check,
                    wait=execution.wait_provider, retry_unknown_transports=False,
                    response_observer=lambda status, limits: _observe_quota(profile, limits)) as adapter:
                send_user = manager.redact(user) if store.setting(workspace,'redact_secrets',True) else user
                raw,usage = adapter.complete(system,send_user)
                metadata = adapter.completion_metadata
                if execution.attempt_log:
                    execution.attempt_log[-1].update(outcome='response_received',usage_known=metadata.get('usage_known',False))
                if execution.attempts - invocation_start > 1:
                    metadata = {**metadata,'usage_known':False}
                execution.check()
                if metadata.get('truncated'):
                    raise ValueError('Provider output truncated')
                if len(raw) > 1024*1024:
                    raise ValueError('Model content exceeds response budget')
                from dataforge.ai_wire import decode_project_result
                validated = decode_project_result(task, response_object(raw), unit, settings=execution.settings)
                if task == 'project_lineage':
                    validated.assert_unit(unit)
                else:
                    validated.assert_candidates({c['candidate_id'] for c in execution.review_candidates})
                    for decision in validated.decisions:
                        for citation in decision.evidence:
                            citation.assert_unit(unit)
        except (ValueError,ProviderError) as exc:
            # Pydantic errors include rejected input values; retain only host error codes.
            outcome = 'quarantined'
            reason = str(exc)[:500] if isinstance(exc, ProviderError) else 'project_response_contract_invalid'
            if isinstance(exc, SourceCitationError):
                reason = str(exc)
            retryable = isinstance(exc, ProviderError) and exc.retryable
        record_id = uuid.uuid4().hex
        details = {'unit_id':unit.unit_id,'content_hash':unit.content_hash,'job_id':unit.job_id,'schema_version':schema_version,'prompt_version':prompt_version,
                   'reason':reason,'attempts':execution.attempts-attempt_start,'requested_model':profile.model,
                   'resolved_model':metadata.get('resolved_model'),'finish_reason':metadata.get('finish_reason'),
                   'usage_known':metadata.get('usage_known',False),'result':None,
                   'physical_attempts':execution.attempt_log[attempt_start:]}
        # Minimal evidence belongs to staged claims; full provider bodies are privacy-opt-in.
        if store.setting(workspace,'llm_history',False):
            details.update(context=user,response=raw)
        safe_details,safe_usage = manager.sanitize(details),manager.sanitize(usage)
        with store.transaction():
            store.execute('INSERT INTO prompt_versions VALUES (?,?,?) ON CONFLICT DO NOTHING',[prompt_hash,task,prompt_version])
            store.execute('INSERT INTO llm_records(record_id,workspace_id,profile_id,task,file_id,start_line,prompt_hash,provider,model,outcome,duration,usage,details) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                [record_id,workspace,pid,task,unit.file_id,unit.first,prompt_hash,profile.provider,profile.model,
                 outcome,time.perf_counter()-started,json.dumps(safe_usage),json.dumps(safe_details)])
        result = UnitAttemptResult(unit_id=unit.unit_id,task=task,result=validated if outcome == 'validated' else None,
            record_id=record_id,outcome=outcome,reason=manager.redact(reason),usage=safe_usage,usage_known=metadata.get('usage_known',False),
            attempts=execution.attempts-invocation_start,requested_model=profile.model,resolved_model=metadata.get('resolved_model'),
            finish_reason=metadata.get('finish_reason'),prompt_hash=prompt_hash)
        expire_ai_history(store, workspace)
        if not retryable:
            return result
    return result


def _observe_quota(profile, limits):
    from dataforge.ai_rate_limits import QUOTAS, quota_scope
    QUOTAS.observe(quota_scope(profile), limits)
