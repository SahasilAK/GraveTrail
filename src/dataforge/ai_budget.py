"""Pure conservative full-envelope allowances and bounded execution recommendations."""
from __future__ import annotations

import json
from dataclasses import dataclass
from math import ceil

HARD_LIMITS = {'max_provider_attempts': 2000, 'max_output_tokens_total': 2000000, 'max_seconds': 14400}
MIN_LIMITS = {'max_provider_attempts': 1, 'max_output_tokens_total': 1000, 'max_seconds': 30}


@dataclass(frozen=True)
class ModelLimits:
    context_tokens: int | None
    input_tokens: int | None
    output_tokens: int
    window: str
    source: str
    dynamic: bool = False


@dataclass(frozen=True)
class RequestBudget:
    input_count: int
    count_method: str
    input_limit: int | None
    output_limit: int
    reserved_output: int
    headroom: int
    fits: bool
    reasons: tuple[str, ...]


def effective_limits(profile):
    caps = profile.model_capabilities
    if caps is None or not caps.current_for(profile):
        return ModelLimits(None, None, profile.max_tokens, 'combined', 'unknown')
    return ModelLimits(caps.context_tokens, caps.input_tokens,
        min(profile.max_tokens, caps.output_tokens or profile.max_tokens), caps.window, caps.source, caps.dynamic)


def count_request_tokens(serialized_request, profile):
    # Only use already loaded matching encodings. Preview must never download assets.
    known = {'gpt-4o': 'o200k_base', 'gpt-4o-mini': 'o200k_base', 'gpt-4.1': 'o200k_base'}
    if profile.provider == 'OpenAI' and profile.model in known:
        try:
            import tiktoken.registry
            encoding = tiktoken.registry.ENCODINGS.get(known[profile.model])
            if encoding is not None:
                return len(encoding.encode(serialized_request, disallowed_special=())) + 256, 'tiktoken_text_plus_estimated_framing'
        except ImportError:
            pass
    return len(serialized_request.encode('utf-8')) + 256, 'utf8_bytes_plus_estimated_framing'


def request_budget(profile, serialized_request, reserved_output, *, disclosed_characters=0):
    """Count the complete provider body, with conservative framing and model headroom."""
    limits = effective_limits(profile)
    count, method = count_request_tokens(serialized_request, profile)
    headroom = max(512, ceil((limits.context_tokens or limits.input_tokens or 0) * .05))
    allowance = limits.input_tokens
    reasons = []
    if limits.window == 'combined' and limits.context_tokens:
        shared = max(0, limits.context_tokens - reserved_output - headroom)
        allowance = min(allowance, shared) if allowance else shared
    elif allowance:
        allowance = max(0, allowance - headroom)
    else:
        reasons.append('model_token_capacity_required')
    if allowance is not None and count > allowance:
        reasons.append('complete_request_exceeds_input_budget')
    if reserved_output > limits.output_tokens or reserved_output < 1:
        reasons.append('reserved_output_exceeds_model_limit')
    if profile.source_limit_policy == 'unconfirmed':
        reasons.append('legacy_source_limit_choice_required')
    elif profile.source_limit_policy == 'explicit':
        if profile.source_disclosure_chars is None:
            reasons.append('explicit_disclosure_limit_required')
        elif disclosed_characters > profile.source_disclosure_chars:
            reasons.append('explicit_disclosure_limit_exceeded')
    return RequestBudget(count, method, allowance, limits.output_tokens, reserved_output,
                         headroom, not reasons, tuple(reasons))


def resolve_project_allowance(bundles, request):
    """Freeze a batch-independent lifetime allowance, separate from execution caps.

    Reserve one repair and two resolution rounds per singleton. Review bundles
    are already included by the caller. No enlargement after dispatch begins.
    """
    totals = tuple(sum(bundle[i] for bundle in bundles) for i in range(3))
    result = {'extraction_attempts': totals[0], 'bounded_extra_rounds': 3}
    for key, total in zip(HARD_LIMITS, totals):
        ceiling = max(MIN_LIMITS[key], ceil(total * 4))
        field = 'project_' + key
        limit = type(request).model_fields[field].metadata[-1].le
        if ceiling > limit:
            raise ValueError('project_allowance_exceeds_application_limit')
        result[key] = getattr(request, field) or ceiling
    return result


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
    source_characters: int
    character_limit: int


def source_characters(user):
    """Disclosed domain content; instructions/schema still count toward model capacity."""
    try:
        context = json.loads(user[user.index('{'):])
        items = context.get('items', [context])
        return sum(len(item.get('unit', {}).get('code', ''))
            + sum(len(segment['code']) for segment in item.get('source_segments', []))
            + sum(len(ref.get('name', '')) + len(ref.get('text', '')) for group in
                  ('expression_references', 'partial_expression_references') for ref in item.get(group, []))
            + len(json.dumps({k: item[k] for k in ('catalog', 'context_records', 'settings', 'resolution', 'candidates')
                if k in item and not (k == 'candidates' and isinstance(item[k], str))},
                ensure_ascii=False, separators=(',', ':'))) for item in items)
    except (ValueError, TypeError, AttributeError):
        return None


def request_allowance(profile, system, user, *, privacy_chars, context_chars=None, reserved_source_chars=0):
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
    source = source_characters(user)
    if source is not None:
        source += reserved_source_chars
    limit = context_chars or min(profile.context_chars, privacy_chars)
    if (chars if source is None else source) > limit:
        reasons.append('complete_prompt_exceeds_context_budget' if source is None
                       else 'source_context_exceeds_character_allowance')
    return RequestAllowance(not reasons, tuple(reasons), estimate.upper_bound, estimate.method, output,
        input_limit, headroom, chars, caps.source if current else 'configured; metadata stale or unavailable',
        caps.dynamic if current else False, chars if source is None else source, limit)


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


def file_sizing(preview):
    """One sortable row per source, with worst planned request and all blockers."""
    rows = {}
    for source in preview.get('disclosure', []):
        rows[source['path']] = {'File': source['path'], 'File characters': source['characters'],
            'Planned tasks': 0, 'Maximum request characters': 0, 'Maximum source/context characters': 0,
            'Source/context character allowance': None, 'Estimated input tokens (upper bound)': 0,
            'Model input token allowance': None, 'Needs attention': ''}
    units = {}
    for allowance in preview.get('allowances', []):
        path = allowance['path']
        if path not in rows:
            continue
        row = rows[path]
        units.setdefault(path, set()).add(allowance['unit_id'])
        for column, field in [('Maximum request characters', 'required_characters'),
                              ('Maximum source/context characters', 'source_characters'),
                              ('Estimated input tokens (upper bound)', 'estimated_input')]:
            row[column] = max(row[column], allowance[field])
        for column, field in [('Source/context character allowance', 'character_limit'),
                              ('Model input token allowance', 'input_limit')]:
            value = allowance[field]
            if value is not None:
                row[column] = value if row[column] is None else min(row[column], value)
        row['Needs attention'] = '; '.join(sorted(set(filter(None,
            [*row['Needs attention'].split('; '), *allowance['reasons']]))))
    for path, ids in units.items():
        rows[path]['Planned tasks'] = len(ids)
    return sorted(rows.values(), key=lambda row: (-row['Maximum request characters'], row['File']))
