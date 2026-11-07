"""Pure conservative full-envelope allowances and bounded execution recommendations."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import ceil
from pathlib import Path


@dataclass(frozen=True)
class ModelLimits:
    context_tokens: int | None
    input_tokens: int | None
    output_tokens: int
    window: str
    source: str
    dynamic: bool = False
    reasoning_reserve: int = 0


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
        min(profile.max_tokens, caps.output_tokens or profile.max_tokens), caps.window, caps.source, caps.dynamic,
        caps.reasoning_tokens if caps.reasoning_accounting == 'shared_context' else 0)


@lru_cache(maxsize=1)
def _offline_openai_encoding():
    try:
        import tiktoken
        from tiktoken.load import load_tiktoken_bpe
    except ImportError:
        return None
    path = Path(__file__).with_name('tokenizer_assets') / 'o200k_base.tiktoken'
    if not path.is_file():
        return None
    patterns = [
        r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]*[\p{Ll}\p{Lm}\p{Lo}\p{M}]+(?i:'s|'t|'re|'ve|'m|'ll|'d)?",
        r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]+[\p{Ll}\p{Lm}\p{Lo}\p{M}]*(?i:'s|'t|'re|'ve|'m|'ll|'d)?",
        r"\p{N}{1,3}", r" ?[^\s\p{L}\p{N}]+[\r\n/]*", r"\s*[\r\n]+", r"\s+(?!\S)", r"\s+",
    ]
    try:
        ranks = load_tiktoken_bpe(str(path), expected_hash='446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d')
        return tiktoken.Encoding('o200k_base', pat_str='|'.join(patterns), mergeable_ranks=ranks,
                                 special_tokens={'<|endoftext|>': 199999, '<|endofprompt|>': 200018})
    except (ValueError, OSError):
        return None


def count_request_tokens(serialized_request, profile):
    # The protocol alone does not establish a tokenizer mapping for a gateway.
    known = {'gpt-4o': 'o200k_base', 'gpt-4o-mini': 'o200k_base', 'gpt-4.1': 'o200k_base'}
    if profile.provider == 'OpenAI' and profile.model in known:
        encoding = _offline_openai_encoding()
        if encoding is not None:
            return len(encoding.encode(serialized_request, disallowed_special=())) + 256, 'tiktoken_text_plus_estimated_framing'
    return len(serialized_request.encode('utf-8')) + 256, 'utf8_bytes_plus_estimated_framing'


def request_budget(profile, serialized_request, reserved_output, *, disclosed_characters=0):
    """Count the complete provider body, with conservative framing and model headroom."""
    limits = effective_limits(profile)
    count, method = count_request_tokens(serialized_request, profile)
    capacity = ((limits.context_tokens or limits.input_tokens) if limits.window == 'combined' or profile.analysis_input_allowance is None
                else (limits.input_tokens or limits.context_tokens))
    headroom = max(512, ceil((capacity or 0) * .05))
    allowance = limits.input_tokens or (limits.context_tokens if limits.window == 'separate' else None)
    reasons = []
    if limits.window == 'combined' and limits.context_tokens:
        shared = max(0, limits.context_tokens - reserved_output - limits.reasoning_reserve - headroom)
        allowance = min(allowance, shared) if allowance else shared
    elif allowance:
        allowance = max(0, allowance - headroom)
    else:
        reasons.append('model_token_capacity_required')
    if profile.analysis_input_allowance is not None:
        # Already allocated after safety/reasoning. Only intersect with the
        # physical allowance above; do not subtract either reserve again.
        allowance = min(allowance, profile.analysis_input_allowance) if allowance is not None else None
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
















def _allocation(capabilities, share, output_capacity=None):
    if capabilities.window == 'combined' and capabilities.context_tokens is None:
        raise ValueError('shared_model_context_capacity_required')
    capacity = ((capabilities.context_tokens or capabilities.input_tokens) if capabilities.window == 'combined'
                else (capabilities.input_tokens or capabilities.context_tokens))
    if not capacity:
        raise ValueError('model_token_capacity_required')
    safety = max(512, ceil(capacity * .05))
    reasoning = capabilities.reasoning_tokens if capabilities.window == 'combined' and capabilities.reasoning_accounting == 'shared_context' else 0
    usable = max(0, capacity - safety - reasoning)
    base = usable if capabilities.window == 'combined' else (capabilities.output_tokens or output_capacity)
    if base is None:
        raise ValueError('separate_model_output_capacity_required')
    return usable, int(base * share / 100), safety, reasoning


def allocate_analysis_profile(profile, request):
    """Deterministic run allocation; the saved provider profile is never mutated."""
    caps = profile.model_capabilities
    if request.budget_policy == 'legacy':
        budget = request_budget(profile, '{}', profile.max_tokens)
        return profile, {'policy': 'legacy', 'input_allowance': budget.input_limit,
                         'output_allowance': profile.max_tokens, 'source': caps.source if caps else 'unknown'}
    if caps is None or not caps.current_for(profile):
        raise ValueError('model_token_capacity_required')
    if caps.dynamic and caps.source != 'manual':
        raise ValueError('dynamic_route_safe_capacity_confirmation_required')
    fallback_output = request.output_token_limit or (profile.max_tokens if profile.output_mode == 'custom' else None)
    usable, preferred, safety, reasoning = _allocation(caps, request.output_share, fallback_output)
    clamps, notes = [], []
    if caps.window == 'separate' and caps.output_tokens is None and profile.output_mode == 'custom':
        preferred = profile.max_tokens
        notes.append('Independent output capacity is unreported; the saved custom output allowance is retained instead of inventing a percentage capacity.')
    output = request.output_token_limit if request.output_token_limit is not None else preferred
    if request.output_token_limit is None and profile.output_mode == 'custom' and output > profile.max_tokens:
        output = profile.max_tokens
        clamps.append('saved_custom_output_limit')
    if caps.output_tokens is not None and output > caps.output_tokens:
        output = caps.output_tokens
        clamps.append('model_output_limit')
    if caps.window == 'combined' and output > usable:
        output = usable
        clamps.append('shared_context_limit')
    input_ = max(0, usable - output) if caps.window == 'combined' else usable
    if caps.window == 'combined' and caps.input_tokens is not None and input_ > caps.input_tokens:
        input_ = caps.input_tokens
        clamps.append('model_input_limit')
    if request.input_token_limit is not None:
        if request.input_token_limit > input_:
            clamps.append('available_input_limit')
        input_ = min(input_, request.input_token_limit)
    if output < 64 or input_ < 1:
        raise ValueError('insufficient_model_token_capacity')
    if caps.output_tokens is None:
        notes.append('Model output limit is unreported; the requested maximum is not a verified provider output capacity.')
    if caps.window == 'separate':
        notes.append('The percentage applies to the independent output capacity; it does not reduce the input window.')
    effective = profile.model_copy(update={'max_tokens': output, 'analysis_input_allowance': input_})
    return effective, {'policy': 'model_share', 'output_share': request.output_share,
        'input_allowance': input_, 'output_allowance': output, 'safety_reserve': safety, 'reasoning_reserve': reasoning,
        'context_capacity': caps.context_tokens, 'input_capacity': caps.input_tokens, 'output_capacity': caps.output_tokens,
        'window': caps.window, 'source': caps.source, 'dynamic': caps.dynamic, 'clamps': clamps, 'notes': notes}


def profile_recommendations(capabilities=None):
    output = 2048  # No capacity has been confirmed; builds still require confirmation.
    if capabilities:
        try:
            _, output, _, _ = _allocation(capabilities, 30)
            if capabilities.output_tokens is not None:
                output = min(output, capabilities.output_tokens)
        except ValueError:
            pass
    output = max(64, output)
    capacity = capabilities.input_tokens or capabilities.context_tokens if capabilities else None
    if capabilities and capabilities.context_tokens and capabilities.window == 'combined':
        capacity = min(capacity, max(0, capabilities.context_tokens - output - max(512, ceil(capabilities.context_tokens * .05))))
    # Four UTF-8 bytes per character plus framing fits the conservative estimator.
    context = max(500, min(200000, (capacity - 256) // 4)) if capacity else 16000
    return {'max_tokens': output, 'context_chars': context}
