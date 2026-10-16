import asyncio
import json
import os

import httpx
import pytest

from dataforge.agent.contracts import AccessPolicy, AgentError
from dataforge.agent.mcp_server import create_server
from dataforge.agent.service import AgentService
from dataforge.llm import Profile
from dataforge.store import Store


def test_profiles_revisions_routing_references_and_network(tmp_path, monkeypatch):
    store = Store(tmp_path)
    w = store.create_workspace('providers')
    canary = 'parity-provider-secret-canary'
    monkeypatch.setenv('OMNIROUTE_API_KEY', canary)
    environment = dict(os.environ)
    policy = AccessPolicy(allow_write=True, allow_config_write=True, allow_llm=True,
        allowed_llm_origins=('http://localhost:20128',), allowed_credential_refs=('OMNIROUTE_API_KEY',))
    service = AgentService(store, policy)
    try:
        revision = service.call('providers_list', w)['settings_revision']
        profile = Profile(provider='OmniRoute', base_url='http://localhost:20128/v1', model='auto/best-reasoning', key_env='OMNIROUTE_API_KEY').model_dump()
        saved = service.call('provider_save', w, profile=profile, expected_revision=revision)
        pid = saved['profile_id']
        with pytest.raises(AgentError):
            service.call('provider_save', w, profile={**profile, 'key_env': 'UNRELATED_SECRET'}, expected_revision=saved['settings_revision'])
        status = service.call('runtime_connect', w, profile_id=pid)
        assert status['connected'] and canary not in json.dumps(status)
        calls = []
        def respond(request):
            calls.append(request)
            assert request.headers['Authorization'] == 'Bearer ' + canary
            return httpx.Response(200, json={'data': [{'id': 'auto/best-reasoning'}]})
        service.provider_transport = httpx.MockTransport(respond)
        actual = asyncio.run(create_server(service).call_tool('discover_provider_models', {'workspace_id': w, 'profile_id': pid}))
        assert not actual.isError and actual.structuredContent['items'] == ['auto/best-reasoning']
        assert len(calls) == 1
        service.call('runtime_clear', w, profile_id=pid)
        assert not service.call('runtime_status', w, profile_id=pid)['connected']
        other = AgentService(store, AccessPolicy())
        try:
            with pytest.raises(AgentError):
                other.call('provider_models', w, profile_id=pid)
        finally:
            other.close()
        assert os.environ == environment
    finally:
        service.close()
        store.close()
    assert canary.encode() not in (tmp_path / 'dataforge.duckdb').read_bytes()
