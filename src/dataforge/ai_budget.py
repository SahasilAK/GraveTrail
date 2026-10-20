"""Pure conservative full-envelope allowances and bounded execution recommendations."""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil

HARD_LIMITS = {'max_provider_attempts': 2000, 'max_output_tokens_total': 2000000, 'max_seconds': 14400}
MIN_LIMITS = {'max_provider_attempts': 1, 'max_output_tokens_total': 1000, 'max_seconds': 30}


@dataclass(frozen=True)
class TokenEstimate:
    upper_bound: int
    method: str = 'utf8_bytes_plus_framing_v1'


def estimate_tokens(*texts):
    # Unknown tokenizer: intentionally conservative, never labelled an exact count.
    return TokenEstimate(sum(len(text.encode('utf-8')) for text in texts) + 256)


@dataclass(frozen=True)
class RequestAllowance:
    valid: bool
    reasons: tuple[str, ...]
    estimated_input: int
    estimate_method: str
    reserved_output: int
    input_limit: int | None
    headroom: int
    required_characters: int
    capacity_source: str
    dynamic: bool


def request_allowance(profile, system, user, *, privacy_chars):
    estimate = estimate_tokens(system, user)
    caps = profile.model_capabilities
    current = caps is not None and caps.current_for(profile)
    output = profile.max_tokens
    headroom = max(512, ceil((caps.context_tokens or caps.input_tokens or 0) * .05)) if current else 512
    input_limit = caps.input_tokens if current else None
    reasons = []
    if current:
        if caps.output_tokens and output > caps.output_tokens:
            reasons.append('configured_output_exceeds_model_limit')
        if caps.context_tokens and caps.window == 'combined':
            shared = max(0, caps.context_tokens - output - headroom)
            input_limit = min(input_limit, shared) if input_limit else shared
        elif input_limit:
            input_limit = max(0, input_limit - headroom)
        if input_limit is not None and estimate.upper_bound > input_limit:
            reasons.append('complete_prompt_exceeds_model_capacity')
    chars = len(system) + len(user)
    if chars > min(profile.context_chars, privacy_chars):
        reasons.append('complete_prompt_exceeds_context_budget')
    return RequestAllowance(not reasons, tuple(reasons), estimate.upper_bound, estimate.method, output,
        input_limit, headroom, chars, caps.source if current else 'configured; metadata stale or unavailable',
        caps.dynamic if current else False)


def execution_budget(bundles, **overrides):
    totals = tuple(sum(bundle[i] for bundle in bundles) for i in range(3))
    keys = tuple(HARD_LIMITS)
    recommended = {key: min(HARD_LIMITS[key], max(MIN_LIMITS[key], ceil(total)))
                   for key, total in zip(keys, totals)}
    effective = {key: recommended[key] if overrides.get(key) is None else overrides[key] for key in keys}
    used = [0, 0, 0]
    selected = 0
    for bundle in bundles:
        if any(used[i] + value > effective[keys[i]] for i, value in enumerate(bundle)):
            break
        used = [used[i] + value for i, value in enumerate(bundle)]
        selected += 1
    return {'recommended': recommended, 'effective': effective, 'selected_units': selected,
            'remaining_units': len(bundles) - selected,
            'selected_new_units': sum(any(bundle) for bundle in bundles[:selected]), 'total_attempts': totals[0],
            'total_output_tokens': totals[1], 'estimate_method': 'utf8_bytes_plus_framing_v1'}


def profile_recommendations(capabilities=None):
    output = min(8192, capabilities.output_tokens) if capabilities and capabilities.output_tokens else 2048
    output = max(64, output)
    capacity = capabilities.input_tokens or capabilities.context_tokens if capabilities else None
    if capabilities and capabilities.context_tokens and capabilities.window == 'combined':
        capacity = min(capacity, max(0, capabilities.context_tokens - output - max(512, ceil(capabilities.context_tokens * .05))))
    # Four UTF-8 bytes per character plus framing fits the conservative estimator.
    context = max(500, min(200000, (capacity - 256) // 4)) if capacity else 16000
    return {'max_tokens': output, 'context_chars': context}


def project_profile(profile, unit):
    if profile.output_mode != 'automatic':
        return profile
    allocation = min(profile.max_tokens, max(1024, 512 + 2 * len(unit.code.encode('utf-8'))))
    return profile.model_copy(update={'max_tokens': allocation})
