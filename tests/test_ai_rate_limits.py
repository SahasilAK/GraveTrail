from email.utils import formatdate


def test_retry_after_seconds_date_and_bad_values():
    from dataforge.ai_rate_limits import normalize_rate_limits, retry_delay
    assert normalize_rate_limits('Anthropic', {'retry-after': '90'}, now=100)['wait_until'] == 190
    assert normalize_rate_limits('Anthropic', {'Retry-After': formatdate(200, usegmt=True)}, now=100)['wait_until'] == 200
    assert retry_delay(0, {}, now=100, jitter=0) == 1
    assert retry_delay(12, {}, now=100, jitter=0) == 60
    assert retry_delay(0, {'retry-after': '90'}, now=100, jitter=0) == 90
    assert retry_delay(0, {'retry-after': 'nan'}, now=100, jitter=0) == 1


def test_input_output_and_request_buckets_gate_independently():
    from dataforge.ai_rate_limits import QuotaRegistry, normalize_rate_limits
    registry = QuotaRegistry()
    snapshot = normalize_rate_limits('Anthropic', {
        'anthropic-ratelimit-requests-remaining': '10',
        'anthropic-ratelimit-input-tokens-remaining': '5',
        'anthropic-ratelimit-input-tokens-reset': '1970-01-01T00:02:00Z',
    }, now=100)
    registry.observe('shared', snapshot)
    assert registry.admit('shared', estimated_input=10, reserved_output=1, now=100) == 120
    assert registry.admit('shared', estimated_input=10, reserved_output=1, now=121) == 121


def test_quota_group_coordinates_profiles_without_secret_identity():
    from dataforge.ai_rate_limits import quota_scope
    from dataforge.llm import Profile
    p = Profile(provider='Ollama', base_url='http://localhost:11434', model='a')
    assert quota_scope(p) == quota_scope(p.model_copy(update={'model': 'b', 'key_env': 'DATAFORGE_OTHER'}))
    assert quota_scope(p.model_copy(update={'quota_group': 'team'})) == 'group:team'
