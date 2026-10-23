"""Allowlisted provider capacity metadata, separate from disclosure and usage limits."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

TokenLimit = Annotated[int, Field(ge=1, le=2_147_483_647)]
IDENTITY_FIELDS = ('provider', 'base_url', 'model', 'auth', 'api_version', 'key_env')
CAPABILITY_MAX_AGE = 24 * 60 * 60


class ModelCapabilities(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    context_tokens: TokenLimit | None = None
    input_tokens: TokenLimit | None = None
    output_tokens: TokenLimit | None = None
    window: Literal['combined', 'separate'] = 'combined'
    dynamic: bool = False
    reasoning_tokens: int = Field(default=0, ge=0)
    reasoning_accounting: Literal['included_output', 'shared_context'] = 'included_output'
    source: Literal['catalog', 'native', 'runtime', 'manual'] = 'catalog'
    observed_at: float = Field(default_factory=time.time, ge=0)
    identity: str = Field(default='', max_length=64)

    def current_for(self, profile, *, now=None):
        age = (time.time() if now is None else now) - self.observed_at
        return self.identity == capability_identity(profile) and (self.source == 'manual' or 0 <= age <= CAPABILITY_MAX_AGE)


class ModelDescriptor(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    id: str = Field(min_length=1, max_length=250)
    capabilities: ModelCapabilities


def capability_identity(profile):
    values = profile if isinstance(profile, dict) else profile.model_dump()
    return hashlib.sha256(json.dumps({k: values.get(k, '') for k in IDENTITY_FIELDS},
                                    sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def bind_capabilities(capabilities, profile):
    return capabilities.model_copy(update={'identity': capability_identity(profile)})


def execution_profile(profile):
    """Observation timestamps/provenance do not change the executable configuration."""
    values = profile if isinstance(profile, dict) else profile.model_dump()
    values = dict(values)
    for key, default in {'connect_timeout': 5, 'read_timeout': None, 'unknown_retries': 0, 'wait_until_stopped': False}.items():
        if values.get(key) == default:
            values.pop(key, None)
    if values.get('model_capabilities'):
        values['model_capabilities'] = {k: v for k, v in values['model_capabilities'].items()
                                      if k not in {'observed_at', 'source'}}
    return values


def runtime_profile(profile):
    # Preserve invalidation on request-option edits; metadata refresh is harmless.
    return profile.model_dump_json(exclude={'model_capabilities'})


def _limit(values):
    valid = [value for value in values if type(value) is int and 0 < value <= 2_147_483_647]
    return min(valid) if valid else None


def normalize_model(item, provider):
    """Unknown/malformed capacities stay unknown; raw provider fields never persist."""
    if not isinstance(item, dict):
        return None
    name = item.get('id', item.get('name'))
    if not isinstance(name, str) or not name.strip() or len(name) > 250 or any(ord(c) < 32 for c in name):
        return None
    nested = [item]
    nested.extend(value for key in ('top_provider', 'limits', 'details')
                  if isinstance(value := item.get(key), dict))

    def limits(*keys):
        return _limit([obj.get(key) for obj in nested for key in keys])

    native = item.get('model_info', {})
    native_context = _limit([value for key, value in native.items() if key.endswith('.context_length')]) if isinstance(native, dict) else None
    context = _limit([limits('context_length', 'context_window', 'contextWindow'), native_context])
    input_tokens = limits('max_input_tokens', 'max_prompt_tokens', 'inputTokenLimit')
    output_tokens = limits('max_output_tokens', 'max_completion_tokens', 'outputTokenLimit')
    return ModelDescriptor(id=name, capabilities=ModelCapabilities(
        context_tokens=context, input_tokens=input_tokens, output_tokens=output_tokens,
        window='separate' if item.get('window_type') == 'separate' else 'combined',
        dynamic=name.startswith(('auto/', 'auto:')) or (provider == 'OmniRoute' and item.get('custom') is True),
        source='native' if native_context else 'catalog'))


def merge_descriptors(descriptors):
    """Duplicates narrow known limits, preserving first-seen model order."""
    result = {}
    for descriptor in descriptors:
        if descriptor is None:
            continue
        old = result.get(descriptor.id)
        if old:
            a, b = old.capabilities, descriptor.capabilities
            descriptor = ModelDescriptor(id=descriptor.id, capabilities=ModelCapabilities(
                context_tokens=_limit([a.context_tokens, b.context_tokens]),
                input_tokens=_limit([a.input_tokens, b.input_tokens]),
                output_tokens=_limit([a.output_tokens, b.output_tokens]),
                window='combined' if 'combined' in {a.window, b.window} else 'separate',
                dynamic=a.dynamic or b.dynamic, source=b.source,
                observed_at=max(a.observed_at, b.observed_at)))
        result[descriptor.id] = descriptor
    return list(result.values())
