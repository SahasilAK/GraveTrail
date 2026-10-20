from dataforge.ai_budget import estimate_tokens, execution_budget, request_allowance
from dataforge.llm import Profile
from dataforge.model_capabilities import ModelCapabilities, bind_capabilities


def profile(**limits):
    p = Profile(provider='OmniRoute', base_url='http://localhost:20128/v1', model='m', context_chars=100000)
    return p.model_copy(update={'model_capabilities': bind_capabilities(ModelCapabilities(**limits), p)})


def test_full_envelope_unicode_combined_and_separate_limits():
    assert estimate_tokens(chr(20013) * 100).upper_bound > estimate_tokens('a' * 100).upper_bound
    p = profile(context_tokens=10000, input_tokens=10000, output_tokens=3000)
    result = request_allowance(p, 'a' * 1000, 'b' * 1000, privacy_chars=100000)
    assert result.valid and result.estimated_input > 2000 and result.reserved_output == 2048
    assert not request_allowance(p, 'a' * 8000, '', privacy_chars=100000).valid
    p = profile(input_tokens=10000, output_tokens=3000, window='separate')
    assert request_allowance(p, 'a' * 8000, '', privacy_chars=100000).valid
    assert not request_allowance(p, 'a' * 1000, '', privacy_chars=500).valid


def test_unknown_or_stale_capacity_never_invents_token_limits():
    p = profile(context_tokens=1000)
    p.model_capabilities = p.model_capabilities.model_copy(update={'observed_at': 0.0})
    result = request_allowance(p, 'a' * 2000, '', privacy_chars=100000)
    assert result.valid and result.capacity_source == 'configured; metadata stale or unavailable'
    assert result.input_limit is None


def test_large_project_stages_complete_unit_bundles_and_auto_budgets():
    bundles = [(4, 8000, 10)] * 1000
    budget = execution_budget(bundles)
    assert budget['selected_units'] == 250 and budget['remaining_units'] == 750
    assert budget['effective']['max_output_tokens_total'] == 2000000
    assert execution_budget(bundles, max_provider_attempts=8)['selected_units'] == 2
    assert execution_budget(bundles, max_output_tokens_total=1000)['selected_units'] == 0
    assert execution_budget([])['selected_units'] == 0
