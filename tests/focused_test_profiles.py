"""Explicitly confirmed offline profiles for focused assistance regressions."""
from dataforge.llm import Profile
from dataforge.model_capabilities import ModelCapabilities, bind_capabilities


def focused_profile(**settings):
    profile = Profile(**{'source_limit_policy': 'token_capacity', **settings})
    profile.model_capabilities = bind_capabilities(ModelCapabilities(context_tokens=100000, source='manual'), profile)
    return profile
