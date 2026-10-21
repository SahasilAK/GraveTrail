import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest

from dataforge.agent.contracts import AccessPolicy, AgentError
from dataforge.agent.mcp_server import create_server
from dataforge.agent.service import AgentService
from dataforge.llm import Profile
from dataforge.store import Store


def test_profiles_revisions_routing_references_and_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that profiles revisions routing references and network.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
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
        def respond(request: pytest.FixtureRequest) -> Any:
            """Handle respond for the test scenario.

            Args:
                request: Pytest fixture describing the active test request.

            Returns:
                Value produced for the test scenario.
            """
            calls.append(request)
            assert request.headers['Authorization'] == 'Bearer ' + canary
            return httpx.Response(200, json={'data': [{'id': 'auto/best-reasoning'}]})
        service.provider_transport = httpx.MockTransport(respond)
        actual = asyncio.run(create_server(service).call_tool('discover_provider_models', {'workspace_id': w, 'profile_id': pid}))
        assert not actual.isError and actual.structuredContent['items'] == ['auto/best-reasoning']
        assert len(calls) == 1
        monkeypatch.setenv('DATAFORGE_OTHER_KEY', 'replacement-profile-canary')
        from dataclasses import replace
        service.policy = replace(policy, allowed_llm_origins=('http://localhost:20128', 'http://localhost:20129'),
            allowed_credential_refs=('OMNIROUTE_API_KEY', 'DATAFORGE_OTHER_KEY'))
        service.call('provider_save', w, profile={**profile, 'base_url': 'http://localhost:20129/v1', 'key_env': 'DATAFORGE_OTHER_KEY'},
            profile_id=pid, expected_revision=service.call('providers_list', w)['settings_revision'])
        recipients = []
        def edited(request: pytest.FixtureRequest) -> Any:
            """Handle edited for the test scenario.

            Args:
                request: Pytest fixture describing the active test request.

            Returns:
                Value produced for the test scenario.
            """
            recipients.append((request.url.port, request.headers['Authorization']))
            return httpx.Response(200, json={'data': []})
        service.provider_transport = httpx.MockTransport(edited)
        service.call('provider_models', w, profile_id=pid)
        assert recipients == [(20129, 'Bearer replacement-profile-canary')]
        environment = dict(os.environ)
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


def test_network_admission_is_immediate_and_does_not_block_settings(tmp_path: Path) -> None:
    """Verify that network admission is immediate and does not block settings.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor
    store = Store(tmp_path)
    w = store.create_workspace('concurrent')
    profile = Profile(provider='OpenAI compatible', base_url='http://localhost:1234/v1', model='test')
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', w, 'p', profile.model_dump_json()])
    service = AgentService(store, AccessPolicy(allow_write=True, allow_llm=True, allowed_llm_origins=('http://localhost:1234',)))
    entered, release = threading.Event(), threading.Event()
    def respond(request: pytest.FixtureRequest) -> Any:
        """Handle respond for the test scenario.

        Args:
            request: Pytest fixture describing the active test request.

        Returns:
            Value produced for the test scenario.
        """
        entered.set()
        release.wait(5)
        return httpx.Response(200, json={'data': []})
    service.provider_transport = httpx.MockTransport(respond)
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            first = pool.submit(service.call, 'provider_models', w, profile_id='p')
            assert entered.wait(3)
            second = pool.submit(service.call, 'provider_models', w, profile_id='p')
            read = pool.submit(service.call, 'settings_get', w, section='privacy')
            try:
                with pytest.raises(AgentError) as caught:
                    second.result(timeout=1)
                assert caught.value.code == 'busy'
                assert read.result(timeout=1)['section'] == 'privacy'
            finally:
                release.set()
                first.result(timeout=3)
    finally:
        release.set()
        service.close()
        store.close()
