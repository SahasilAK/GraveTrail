import json

import pytest

from dataforge.ai_budget import effective_limits, request_budget
from dataforge.llm import Profile
from dataforge.model_capabilities import ModelCapabilities, bind_capabilities


def model(context=70000, **limits):
    profile = Profile(provider='OpenAI compatible', base_url='http://localhost:1234', model='unknown',
                      max_tokens=8000, source_limit_policy='token_capacity')
    return profile.model_copy(update={'model_capabilities': bind_capabilities(
        ModelCapabilities(context_tokens=context, source='manual', **limits), profile)})


@pytest.mark.parametrize(('context', 'allowance'), [(70000, 58500), (200000, 182000), (1000000, 942000)])
def test_combined_capacity_counts_complete_request_without_character_ceiling(context, allowance):
    profile = model(context)
    budget = request_budget(profile, json.dumps({'source': 'x' * 10000}), 8000)
    assert budget.input_limit == allowance
    assert budget.fits
    assert budget.input_count > 10000
    assert budget.count_method.endswith('estimated_framing')


def test_separate_windows_and_lower_limits():
    profile = model(input_tokens=20000, output_tokens=9000, window='separate')
    assert request_budget(profile, '{}', 8000).input_limit == 16500
    assert not request_budget(profile, '{}', 10000).fits
    assert effective_limits(model(input_tokens=10000)).input_tokens == 10000


def test_unknown_capacity_and_unconfirmed_disclosure_are_blocking():
    profile = Profile(provider='Ollama', base_url='http://localhost:11434', model='m')
    assert 'model_token_capacity_required' in request_budget(profile, '{}', 2048).reasons
    assert 'legacy_source_limit_choice_required' in request_budget(profile, '{}', 2048).reasons


def test_unicode_and_explicit_disclosure_limit():
    profile = model().model_copy(update={'source_limit_policy': 'explicit', 'source_disclosure_chars': 100})
    budget = request_budget(profile, '界' * 90, 8000, disclosed_characters=90)
    assert budget.input_count >= 270
    assert budget.fits
    assert not request_budget(profile, 'x' * 101, 8000, disclosed_characters=101).fits


def test_manual_capacity_survives_age_but_not_endpoint_change():
    profile = model()
    caps = profile.model_capabilities.model_copy(update={'observed_at': 1.0})
    profile = Profile.model_validate({**profile.model_dump(), 'model_capabilities': caps})
    assert effective_limits(profile).context_tokens == 70000
    changed = Profile.model_validate({**profile.model_dump(), 'model': 'different'})
    assert effective_limits(changed).context_tokens is None


def test_unknown_compatible_model_never_loads_openai_tokenizer(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, 'tiktoken', None)
    assert request_budget(model(), 'source', 8000).count_method == 'utf8_bytes_plus_estimated_framing'


def test_reasoning_reservation_is_subtracted_only_when_separately_accounted():
    included = model(reasoning_tokens=2000, reasoning_accounting='included_output')
    separate = model(reasoning_tokens=2000, reasoning_accounting='shared_context')
    assert request_budget(included, '{}', 8000).input_limit == 58500
    assert request_budget(separate, '{}', 8000).input_limit == 56500


def test_matching_optional_tokenizer_works_offline_with_pinned_asset(monkeypatch):
    pytest.importorskip('tiktoken')
    import requests
    monkeypatch.setattr(requests, 'get', lambda *a, **k: pytest.fail('Encoding downloaded during preview'))
    profile = Profile(provider='OpenAI', base_url='https://api.openai.com/v1', model='gpt-4o',
                      max_tokens=8000, source_limit_policy='token_capacity')
    profile.model_capabilities = bind_capabilities(ModelCapabilities(context_tokens=70000, source='manual'), profile)
    budget = request_budget(profile, 'hello world ' * 100, 8000)
    assert budget.fits
    assert budget.count_method == 'tiktoken_text_plus_estimated_framing'
    assert budget.input_count < len(('hello world ' * 100).encode())
