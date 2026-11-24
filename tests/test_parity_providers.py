import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from dataforge.agent.contracts import AccessPolicy, AgentError
from dataforge.agent.mcp_server import create_server
from dataforge.agent.service import AgentService
from dataforge.ai_budget import profile_recommendations
from dataforge.cli import app
from dataforge.llm import Profile
from dataforge.model_capabilities import ModelCapabilities, capability_identity
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


def test_provider_preflight_and_automatic_limits_workflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    origin = 'http://localhost:11434'
    reference = 'DATAFORGE_DRAFT_KEY'
    secret = 'draft-credential-canary'
    monkeypatch.setenv(reference, secret)
    store = Store(tmp_path)
    workspace = store.create_workspace('provider setup')
    service = AgentService(store, AccessPolicy(allow_write=True, allow_config_write=True, allow_llm=True,
        allowed_llm_origins=(origin,), allowed_credential_refs=(reference,)))
    draft = {'provider': 'Ollama', 'base_url': origin + '/', 'key_env': reference}
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        requests.append(path)
        assert request.headers['Authorization'] == f'Bearer {secret}'
        if path == '/api/tags':
            return httpx.Response(200, json={'models': [{'name': 'candidate'}]})
        if path == '/api/show':
            assert json.loads(request.content) == {'model': 'other'}
            return httpx.Response(200, json={'model_info': {'family.context_length': 8192}, 'ignored': secret})
        if path == '/api/ps':
            return httpx.Response(200, json={'models': [{'name': 'other', 'context_length': 4096}]})
        assert path == '/api/chat' and json.loads(request.content)['model'] == 'candidate'
        return httpx.Response(200, json={'message': {'content': '{"status":"connected"}'}})

    transport = httpx.MockTransport(respond)
    service.provider_transport = transport
    try:
        server = create_server(service)
        discovered = asyncio.run(server.call_tool('discover_provider_models', {
            'workspace_id': workspace, 'draft_profile': draft,
        }))
        assert not discovered.isError and discovered.structuredContent['items'] == ['candidate']
        tested = asyncio.run(server.call_tool('test_provider_connection', {
            'workspace_id': workspace, 'draft_profile': {**draft, 'model': 'candidate'},
        }))
        assert not tested.isError and tested.structuredContent['connected']
        denied = asyncio.run(server.call_tool('discover_provider_models', {
            'workspace_id': workspace, 'draft_profile': {**draft, 'base_url': 'http://localhost:9876'},
        }))
        assert denied.isError and denied.structuredContent['error']['code'] == 'network_not_allowed'
        listed = service.call('providers_list', workspace)
        assert not listed['items'] and requests == ['/api/tags', '/api/chat']

        saved = service.call('provider_save', workspace, expected_revision=listed['settings_revision'], profile={
            **draft, 'model': 'candidate', 'max_tokens': 999,
            'source_limit_policy': 'explicit', 'source_disclosure_chars': 1000,
            'model_capabilities': {'source': 'manual', 'context_tokens': 8192, 'output_tokens': 1500},
        })
        profile_id = saved['profile_id']
        args = {'workspace_id': workspace, 'profile_id': profile_id}
        inspected = asyncio.run(server.call_tool('inspect_provider_model', {**args, 'model': 'other'}))
        assert not inspected.isError and requests[-2:] == ['/api/show', '/api/ps']
        descriptor = inspected.structuredContent['model']
        normalized = Profile.model_validate({**draft, 'model': 'other'})
        assert descriptor['id'] == 'other'
        assert descriptor['capabilities']['context_tokens'] == 4096
        assert descriptor['capabilities']['source'] == 'runtime'
        assert descriptor['capabilities']['identity'] == capability_identity(normalized)
        assert secret not in json.dumps(inspected.structuredContent)

        reset_args = {**args, 'expected_revision': saved['settings_revision']}
        reset = asyncio.run(server.call_tool('reset_provider_profile_limits', reset_args))
        assert not reset.isError
        stored = service.call('provider_get', workspace, profile_id=profile_id)['profile']
        manual = ModelCapabilities.model_validate(stored['model_capabilities'])
        assert stored['model'] == 'candidate' and stored['base_url'] == origin
        assert manual.context_tokens == 8192 and manual.identity == capability_identity(stored)
        recommended = profile_recommendations(manual)
        assert {key: stored[key] for key in recommended} == recommended
        assert stored['output_mode'] == stored['context_mode'] == 'automatic'
        assert stored['source_limit_policy'] == 'explicit' and stored['source_disclosure_chars'] == 1000
        stale = asyncio.run(server.call_tool('reset_provider_profile_limits', reset_args))
        assert stale.isError and stale.structuredContent['error']['code'] == 'conflict'
    finally:
        service.close()
        store.close()

    original = AgentService.__init__

    def with_transport(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self.provider_transport = transport

    monkeypatch.setattr(AgentService, '__init__', with_transport)
    draft_file = tmp_path / 'draft.json'
    draft_file.write_text(json.dumps({**draft, 'key_env': ''}), encoding='utf-8')
    runner = CliRunner()
    launch = ['--home', str(tmp_path), '--json', '--allow-write']
    checked = runner.invoke(app, [*launch, '--allow-llm', '--allowed-llm-origin', origin,
        'providers', 'models', '-w', workspace, '--draft', str(draft_file), '--credential-prompt'], input=secret + '\n')
    assert checked.exit_code == 0 and secret not in checked.output, checked.output.replace(secret, '[redacted]')
    assert json.loads(checked.stdout)['items'] == ['candidate']
    updated = runner.invoke(app, [*launch, '--allow-config-write', '--allowed-credential-ref', reference,
        'providers', 'reset-limits', profile_id, '-w', workspace,
        '--expected-revision', reset.structuredContent['settings_revision']])
    assert updated.exit_code == 0, updated.output
    assert json.loads(updated.stdout)['settings_revision'] == reset.structuredContent['settings_revision']
