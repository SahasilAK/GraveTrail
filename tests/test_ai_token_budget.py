

from dataforge.ai_budget import effective_limits, request_budget
from dataforge.llm import Profile
from dataforge.model_capabilities import ModelCapabilities, bind_capabilities


def model(context=70000, **limits):
    profile = Profile(provider='OpenAI compatible', base_url='http://localhost:1234', model='unknown',
                      max_tokens=8000, source_limit_policy='token_capacity')
    return profile.model_copy(update={'model_capabilities': bind_capabilities(
        ModelCapabilities(context_tokens=context, source='manual', **limits), profile)})


def test_unknown_capacity_and_unconfirmed_disclosure_are_blocking():
    profile = Profile(provider='Ollama', base_url='http://localhost:11434', model='m')
    assert 'model_token_capacity_required' in request_budget(profile, '{}', 2048).reasons
    assert 'legacy_source_limit_choice_required' in request_budget(profile, '{}', 2048).reasons


def test_manual_capacity_survives_age_but_not_endpoint_change():
    profile = model()
    caps = profile.model_capabilities.model_copy(update={'observed_at': 1.0})
    profile = Profile.model_validate({**profile.model_dump(), 'model_capabilities': caps})
    assert effective_limits(profile).context_tokens == 70000
    changed = Profile.model_validate({**profile.model_dump(), 'model': 'different'})
    assert effective_limits(changed).context_tokens is None
