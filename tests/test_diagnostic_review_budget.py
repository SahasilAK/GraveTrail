"""Diagnostic previews and dispatch size the same complete, privacy-gated request."""
import json

import httpx
import pytest
from test_assistance_queue import queued as queued_fixture

from dataforge.assistance_queue import diagnostic_queue, request_review
from dataforge.ingestion import Importer
from dataforge.llm import Profile
from dataforge.model_capabilities import ModelCapabilities, bind_capabilities
from dataforge.services import analyze

queued = queued_fixture


def configure(store, workspace, capacity=100000, **updates):
    profile = Profile(provider='OmniRoute', base_url='http://localhost:20128/v1', model='synthetic',
                      context_chars=500, output_mode='automatic', source_limit_policy='token_capacity', **updates)
    profile.model_capabilities = bind_capabilities(ModelCapabilities(context_tokens=capacity, source='manual'), profile)
    store.execute('UPDATE llm_profiles SET config=? WHERE workspace_id=?', [profile.model_dump_json(), workspace])
    return profile


def preview(store, workspace, item, first=1, last=1):
    from dataforge.assistance_queue import preview_review
    return preview_review(store, workspace, item['diagnostic_id'], first, last)


def test_long_source_fits_and_preview_matches_actual_provider_body(queued):
    store, w, code = queued
    configure(store, w)
    code += ' -- ' + 'source context ' * 1000
    Importer(store, w).files([('q.sql', (code + '\nSELECT 1;').encode())], {'.sql'})
    analyze(store, w)
    item = diagnostic_queue(store, w)['items'][0]
    before = store.rows('SELECT * FROM llm_records')
    p = preview(store, w, item)
    b = p['budget']
    assert b['fits'] and b['estimated_input_tokens'] > 8000
    assert b['reserved_output'] == 28500 and b['input_allowance'] == 66500
    assert store.rows('SELECT * FROM llm_records') == before
    seen = []

    def provider(request):
        body = json.loads(request.content)
        seen.append(body)
        assert body['max_tokens'] == b['reserved_output']
        assert len(json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode()) + 256 == b['estimated_input_tokens']
        context = json.loads(body['messages'][1]['content'].split('\n', 1)[-1])
        assert context['source'] == code and context['start_line'] == context['end_line'] == 1
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"claims": []}'}}]})

    result = request_review(store, w, item['diagnostic_id'], item['content_hash'], 1, 1,
                            transport=httpx.MockTransport(provider))
    assert result['outcome'] == 'validated' and len(seen) == 1
    assert result['budget'] == b
    saved = Profile.model_validate_json(store.rows('SELECT config FROM llm_profiles')[0]['config'])
    assert saved.max_tokens == 2048 and saved.analysis_input_allowance is None


def test_short_source_with_large_instruction_overhead_is_blocked_offline(queued, tmp_path, monkeypatch):
    from dataforge.llm import PROMPTS

    store, w, _ = queued
    configure(store, w, 10000)
    task_prompts = tmp_path / 'large_prompts' / 'sql_lineage'
    task_prompts.mkdir(parents=True)
    (task_prompts / 'system.md').write_text((PROMPTS / 'sql_lineage' / 'system.md').read_text() + ' instructions' * 1000)
    (task_prompts / 'user_template.md').write_text((PROMPTS / 'sql_lineage' / 'user_template.md').read_text())
    monkeypatch.setattr('dataforge.llm.PROMPTS', task_prompts.parent)
    item = diagnostic_queue(store, w)['items'][0]
    p = preview(store, w, item)
    assert not p['budget']['fits']
    assert 'complete_request_exceeds_input_budget' in p['budget']['blocking_reasons']
    with pytest.raises(ValueError, match='complete_request_exceeds_input_budget'):
        request_review(store, w, item['diagnostic_id'], item['content_hash'], 1, 1,
                       transport=httpx.MockTransport(lambda r: pytest.fail('blocked before network')))
    assert not store.rows('SELECT * FROM llm_records')


def test_unrelated_estate_does_not_inflate_selected_review(queued):
    store, w, _ = queued
    configure(store, w)
    item = diagnostic_queue(store, w)['items'][0]
    before = preview(store, w, item)['budget']
    store.execute("""INSERT INTO assets
        SELECT 'unrelated-'||i, ?, 'other.unrelated_long_catalog_name_'||i,
               'other.unrelated_long_catalog_name_'||i, 'table', false, '{}' FROM range(3000) t(i)""", [w])
    after = preview(store, w, item)['budget']
    assert before['estimated_input_tokens'] == after['estimated_input_tokens']
    assert after['fits'] and after['context_scope']['available_assets'] == before['context_scope']['available_assets'] + 3000
    assert before['context_scope']['prompt_assets'] == after['context_scope']['prompt_assets'] == 2


@pytest.mark.parametrize('code,known,selected', [
    ('select * from `Raw`.`Orders`;', {'Raw.Orders', 'Raw.Orders_extra'}, {'Raw.Orders'}),
    ('select * from "Raw"."Order history";', {'Raw.Order history', 'Other.Order history'}, {'Raw.Order history'}),
    ('data work.out; set raw.in; run;', {'work.out', 'raw.in', 'other.in'}, {'work.out', 'raw.in'}),
    ('select * into #temp from raw.a;', {'#temp', 'raw.a', 'temp'}, {'#temp', 'raw.a'}),
    ("select * from raw.a; -- from raw.comment\n/* from raw.block */\nselect 'raw.literal';",
     {'raw.a', 'raw.comment', 'raw.block', 'raw.literal'}, {'raw.a'}),
])
def test_review_catalog_uses_exact_lexical_names(code, known, selected):
    from dataforge.ai_context_index import referenced_asset_names

    assert set(referenced_asset_names(code, known)) == selected


def test_referenced_catalog_and_source_are_never_pruned_to_force_a_fit(queued):
    from dataforge.llm import prepare_assistance

    store, w, code = queued
    profile = configure(store, w, 10000)
    names = {f'catalog.table_{i:03d}_' + 'descriptive_name_' * 5 for i in range(30)}
    code += '\n' + '\n'.join(f'SELECT id FROM {name};' for name in sorted(names))
    Importer(store, w).files([('q.sql', code.encode())], {'.sql'})
    analyze(store, w)
    item = diagnostic_queue(store, w)['items'][0]
    prepared = prepare_assistance(store, w, profile, item['file_id'], 1, 31, 'sql_lineage')
    context = json.loads(prepared['user'].split('\n', 1)[-1])
    assert context['source'] == code
    assert set(context['known_assets']) == names | {'mart.x', 'raw.a'}
    assert not prepared['budget']['fits']
    with pytest.raises(ValueError, match='complete_request_exceeds_input_budget'):
        request_review(store, w, item['diagnostic_id'], item['content_hash'], 1, 31,
                       transport=httpx.MockTransport(lambda r: pytest.fail('blocked before network')))


@pytest.mark.parametrize('policy,limit,reason', [
    ('explicit', 10, 'explicit_disclosure_limit_exceeded'),
    ('explicit', None, 'explicit_disclosure_limit_required'),
    ('unconfirmed', None, 'legacy_source_limit_choice_required'),
])
def test_disclosure_choices_block_preview_and_dispatch(queued, policy, limit, reason):
    store, w, _ = queued
    p = configure(store, w)
    p = p.model_copy(update={'source_limit_policy': policy, 'source_disclosure_chars': limit})
    store.execute('UPDATE llm_profiles SET config=?', [p.model_dump_json()])
    item = diagnostic_queue(store, w)['items'][0]
    assert reason in preview(store, w, item)['budget']['blocking_reasons']
    with pytest.raises(ValueError, match=reason):
        request_review(store, w, item['diagnostic_id'], item['content_hash'], 1, 1,
                       transport=httpx.MockTransport(lambda r: pytest.fail('blocked before network')))


@pytest.mark.parametrize('kind', ['missing', 'stale', 'dynamic'])
def test_unconfirmed_capacity_is_actionable(queued, kind):
    store, w, _ = queued
    p = configure(store, w)
    p.model_capabilities = None if kind == 'missing' else p.model_capabilities.model_copy(update={
        'source': 'catalog', 'observed_at': 1.0 if kind == 'stale' else p.model_capabilities.observed_at,
        'dynamic': kind == 'dynamic'})
    store.execute('UPDATE llm_profiles SET config=?', [p.model_dump_json()])
    item = diagnostic_queue(store, w)['items'][0]
    b = preview(store, w, item)['budget']
    assert not b['fits'] and 'Connections & AI' in ' '.join(b['messages'])
    with pytest.raises(ValueError, match='capacity'):
        request_review(store, w, item['diagnostic_id'], item['content_hash'], 1, 1)


@pytest.mark.parametrize('fallback_capacity,expected_calls', [(10000, 1), (50000, 2)])
def test_task_route_and_fallback_use_their_own_capacity(queued, fallback_capacity, expected_calls):
    store, w, _ = queued
    p = configure(store, w)
    code = 'CREATE TABLE mart.x AS SELECT unknown.id FROM raw.a; -- ' + 'context ' * 1600
    Importer(store, w).files([('q.sql', (code + '\nSELECT 1;').encode())], {'.sql'})
    analyze(store, w)
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['project', w, 'project',
        p.model_copy(update={'model': 'project-only', 'model_capabilities': None}).model_dump_json()])
    fallback = p.model_copy(update={'model': 'small', 'retries': 0, 'max_tokens': 512, 'output_mode': 'custom'})
    fallback.model_capabilities = bind_capabilities(ModelCapabilities(context_tokens=fallback_capacity, source='manual'), fallback)
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['small', w, 'small', fallback.model_dump_json()])
    store.set_setting(w, 'default_profile', 'project')
    store.set_setting(w, 'task_models', {'project_lineage': 'project', 'sql_lineage': 'test-profile'})
    store.set_setting(w, 'fallback_profiles', ['small'])
    item = diagnostic_queue(store, w)['items'][0]
    assert preview(store, w, item)['budget']['model'] == 'synthetic'
    calls = []

    def provider(r):
        body = json.loads(r.content)
        calls.append(body['model'])
        if body['model'] == 'synthetic':
            return httpx.Response(503)
        assert body['model'] == 'small' and body['max_tokens'] == 512
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"claims": []}'}}]})

    p.retries = 0
    store.execute('UPDATE llm_profiles SET config=? WHERE profile_id=?', [p.model_dump_json(), 'test-profile'])
    if expected_calls == 1:
        with pytest.raises(ValueError, match='complete_request_exceeds_input_budget'):
            request_review(store, w, item['diagnostic_id'], item['content_hash'], 1, 1,
                           transport=httpx.MockTransport(provider))
    else:
        result = request_review(store, w, item['diagnostic_id'], item['content_hash'], 1, 1,
                                transport=httpx.MockTransport(provider))
        assert result['budget']['model'] == 'small' and result['budget']['reserved_output'] == 512
    assert len(calls) == expected_calls


def test_saved_custom_reasoning_and_safety_are_applied_once(queued):
    store, w, _ = queued
    p = configure(store, w)
    p = p.model_copy(update={'output_mode': 'custom', 'max_tokens': 4000, 'analysis_input_allowance': 1})
    p.model_capabilities = p.model_capabilities.model_copy(update={
        'reasoning_tokens': 2000, 'reasoning_accounting': 'shared_context'})
    store.execute('UPDATE llm_profiles SET config=?', [p.model_dump_json()])
    item = diagnostic_queue(store, w)['items'][0]
    b = preview(store, w, item)['budget']
    assert b['fits'] and b['reserved_output'] == 4000
    assert b['input_allowance'] == 89000 and b['safety_reserve'] == 5000
    assert b['allocation']['reasoning_reserve'] == 2000


def test_preview_redacts_and_dispatch_rechecks_changed_privacy_and_capacity(queued):
    from dataforge.connections import RuntimeConnections, connection_scope

    store, w, _ = queued
    p = configure(store, w)
    secret = 'synthetic-review-budget-secret'
    code = f'CREATE TABLE mart.x AS SELECT unknown.id FROM raw.a; -- {secret}'
    Importer(store, w).files([('q.sql', (code + '\nSELECT 1;').encode())], {'.sql'})
    analyze(store, w)
    item = diagnostic_queue(store, w)['items'][0]
    manager = RuntimeConnections()
    manager.register('DATAFORGE_REVIEW_TEST_SECRET', secret)
    with connection_scope(manager):
        result = preview(store, w, item)
        assert result['budget']['fits'] and secret not in result['code']

        def provider(r):
            assert secret not in r.content.decode()
            return httpx.Response(200, json={'choices': [{'message': {'content': 'not valid JSON'}}]})

        store.set_setting(w, 'llm_history', True)
        sent = request_review(store, w, item['diagnostic_id'], item['content_hash'], 1, 1,
                              transport=httpx.MockTransport(provider))
        assert sent['outcome'] == 'quarantined' and sent['budget'] == result['budget']
        assert secret not in json.dumps(store.rows('SELECT details FROM llm_records'))
    manager.clear()
    p.source_disclosure_chars, p.source_limit_policy = 10, 'explicit'
    store.execute('UPDATE llm_profiles SET config=?', [p.model_dump_json()])
    with pytest.raises(ValueError, match='explicit_disclosure_limit_exceeded'):
        request_review(store, w, item['diagnostic_id'], item['content_hash'], 1, 1)
    p.source_limit_policy = 'token_capacity'
    p.model_capabilities = None
    store.execute('UPDATE llm_profiles SET config=?', [p.model_dump_json()])
    with pytest.raises(ValueError, match='capacity'):
        request_review(store, w, item['diagnostic_id'], item['content_hash'], 1, 1)


@pytest.mark.parametrize('blocked', [False, True])
def test_streamlit_cli_and_mcp_expose_the_same_offline_budget(queued, monkeypatch, blocked):
    import asyncio

    from streamlit.testing.v1 import AppTest
    from typer.testing import CliRunner

    from dataforge.agent.mcp_server import create_server
    from dataforge.agent.service import AgentService
    from dataforge.cli import app

    store, w, _ = queued
    profile = configure(store, w)
    if blocked:
        profile.source_limit_policy = 'unconfirmed'
        store.execute('UPDATE llm_profiles SET config=?', [profile.model_dump_json()])
    item = diagnostic_queue(store, w)['items'][0]
    expected = preview(store, w, item)['budget']
    monkeypatch.setattr('dataforge.llm.Adapter.complete', lambda *a, **kw: pytest.fail('preview called provider'))
    service = AgentService(store)
    try:
        server = create_server(service)
        response = asyncio.run(server.call_tool('preview_diagnostic_review',
            {'workspace_id': w, 'diagnostic_id': item['diagnostic_id'], 'first': 1, 'last': 1}))
        assert not response.isError
        assert response.structuredContent['budget'] == expected
        assert response.structuredContent['items'][0]['first'] == 1
        cli = CliRunner().invoke(app, ['--home', str(store.home), '--json', 'ai', 'review', 'preview',
            item['diagnostic_id'], '--workspace', w, '--first', '1', '--last', '1'])
        assert cli.exit_code == 0, cli.stdout
        assert json.loads(cli.stdout)['budget'] == expected
        script = (f'from dataforge.store import Store\nfrom ui.unresolved_review import render\n'
                  f'store = Store({str(store.home)!r})\ntry:\n    render(store, {w!r})\nfinally:\n    store.close()')
        view = AppTest.from_string(script, default_timeout=20).run()
        assert not view.exception
        button = next(b for b in view.button if b.label == 'Request AI review of this range')
        assert button.disabled == blocked
        assert any(str(expected['estimated_input_tokens']) in c.value and 'estimated input' in c.value for c in view.caption)
        assert any('names referenced in this range' in c.value for c in view.caption)
        if blocked:
            assert any('legacy_source_limit_choice_required' in m.value for m in view.warning)
        assert not store.rows('SELECT * FROM llm_records')
    finally:
        service.close()


def test_agent_dispatch_uses_budget_with_authorized_runtime_credentials(queued, monkeypatch):
    from dataforge.agent.contracts import AccessPolicy
    from dataforge.agent.service import AgentService

    store, w, _ = queued
    p = configure(store, w, key_env='DATAFORGE_REVIEW_KEY')
    monkeypatch.setenv(p.key_env, 'synthetic-review-credential')
    item = diagnostic_queue(store, w)['items'][0]
    expected = preview(store, w, item)['budget']
    policy = AccessPolicy(allow_write=True, allow_llm=True,
        allowed_llm_origins=(p.base_url,), allowed_credential_refs=(p.key_env,))
    service = AgentService(store, policy)

    def provider(r):
        assert r.headers['Authorization'] == 'Bearer synthetic-review-credential'
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"claims": []}'}}]})

    service.provider_transport = httpx.MockTransport(provider)
    try:
        result = service.call('review_request', w, diagnostic_id=item['diagnostic_id'],
                              expected_hash=item['content_hash'], first=1, last=1)
        assert result['outcome'] == 'validated' and result['budget'] == expected
    finally:
        service.close()


def test_agent_runtime_secret_is_redacted_identically_in_preview_and_dispatch(queued):
    from dataforge.agent.contracts import AccessPolicy
    from dataforge.agent.service import AgentService
    from dataforge.connections import RuntimeConnections
    from dataforge.model_capabilities import runtime_profile

    store, w, _ = queued
    p = configure(store, w, key_env='DATAFORGE_REVIEW_RUNTIME_KEY')
    secret = 'synthetic-session-review-secret'
    code = f'CREATE TABLE mart.x AS SELECT unknown.id FROM raw.a; -- {secret}'
    Importer(store, w).files([('q.sql', (code + '\nSELECT 1;').encode())], {'.sql'})
    analyze(store, w)
    item = diagnostic_queue(store, w)['items'][0]
    service = AgentService(store, AccessPolicy(allow_write=True, allow_llm=True,
        allowed_llm_origins=(p.base_url,), allowed_credential_refs=(p.key_env,)))
    manager = RuntimeConnections()
    manager.register('DATAFORGE_RUNTIME_CREDENTIAL', secret)
    service.runtime_connections[w, 'test-profile'] = manager
    service.runtime_profiles[w, 'test-profile'] = runtime_profile(p)
    service.provider_transport = httpx.MockTransport(lambda r: httpx.Response(200,
        json={'choices': [{'message': {'content': '{"claims": []}'}}]}))
    try:
        result = service.call('review_preview', w, diagnostic_id=item['diagnostic_id'], first=1, last=1)
        assert secret not in json.dumps(result)
        sent = service.call('review_request', w, diagnostic_id=item['diagnostic_id'],
                            expected_hash=item['content_hash'], first=1, last=1)
        assert sent['budget'] == result['budget']
        assert manager.registered('DATAFORGE_RUNTIME_CREDENTIAL')
    finally:
        service.close()


@pytest.mark.parametrize('change', ['source', 'privacy', 'capacity'])
def test_retry_revalidates_before_any_second_transmission(queued, monkeypatch, change):
    store, w, _ = queued
    p = configure(store, w)
    item = diagnostic_queue(store, w)['items'][0]
    calls = []
    monkeypatch.setattr('dataforge.llm.Adapter._wait', lambda *args: None)

    def provider(r):
        calls.append(r)
        if change == 'source':
            Importer(store, w).files([('q.sql', b'SELECT changed FROM raw.changed;')], {'.sql'})
        elif change == 'capacity':
            p.model_capabilities = None
            store.execute('UPDATE llm_profiles SET config=?', [p.model_dump_json()])
        else:
            # A remote profile is allowed initially and denied before retry.
            store.set_setting(w, 'external_llm', False)
        return httpx.Response(503)

    if change == 'privacy':
        p.base_url = 'https://review.example.test/v1'
        p.model_capabilities = bind_capabilities(ModelCapabilities(context_tokens=100000, source='manual'), p)
        store.execute('UPDATE llm_profiles SET config=?', [p.model_dump_json()])
        store.set_setting(w, 'external_llm', True)
    result = request_review(store, w, item['diagnostic_id'], item['content_hash'], 1, 1,
                            transport=httpx.MockTransport(provider))
    assert len(calls) == 1 and result['outcome'] == 'quarantined' and not result['retryable']


def test_unconfigured_preview_keeps_exact_offline_selection(queued):
    store, w, _ = queued
    item = diagnostic_queue(store, w)['items'][0]
    store.execute('DELETE FROM llm_profiles WHERE workspace_id=?', [w])
    result = preview(store, w, item, 2, 2)
    assert result['code'] == 'CREATE TABLE mart.y AS SELECT id FROM raw.b;'
    assert not result['budget']['fits'] and 'Connections & AI' in result['budget']['messages'][0]


def test_full_source_privacy_still_blocks_with_sufficient_model_capacity(queued):
    store, w, _ = queued
    p = configure(store, w)
    p.base_url = 'https://review.example.test/v1'
    p.model_capabilities = bind_capabilities(ModelCapabilities(context_tokens=100000, source='manual'), p)
    store.execute('UPDATE llm_profiles SET config=?', [p.model_dump_json()])
    store.set_setting(w, 'external_llm', True)
    item = diagnostic_queue(store, w)['items'][0]
    assert 'Complete source transmission is disabled' in preview(store, w, item, 1, 2)['budget']['messages'][0]
    with pytest.raises(ValueError, match='Complete source transmission is disabled'):
        request_review(store, w, item['diagnostic_id'], item['content_hash'], 1, 2,
                       transport=httpx.MockTransport(lambda r: pytest.fail('privacy blocked before network')))
    store.set_setting(w, 'allow_full_source', True)
    assert preview(store, w, item, 1, 2)['budget']['fits']


@pytest.mark.parametrize('same_recipient', [True, False])
def test_review_fallback_keeps_recipient_and_authorization_gates(queued, same_recipient):
    from dataforge.agent.contracts import AgentError
    from dataforge.llm import assist_task

    store, w, _ = queued
    p = configure(store, w, retries=0)
    fallback = p.model_copy(update={'model': 'fallback',
        'base_url': p.base_url if same_recipient else 'https://other.example.test/v1'})
    fallback.model_capabilities = bind_capabilities(ModelCapabilities(context_tokens=100000, source='manual'), fallback)
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['fallback', w, 'fallback', fallback.model_dump_json()])
    store.set_setting(w, 'fallback_profiles', ['fallback'])
    item = diagnostic_queue(store, w)['items'][0]
    authorized, calls = [], []

    def authorize(pid, profile):
        authorized.append(pid)
        if pid == 'fallback':
            raise AgentError('network_not_allowed', 'Fallback not authorized')
        return profile

    def provider(r):
        calls.append(r)
        return httpx.Response(503)

    args = (store, w, item['file_id'], 1, 1, 'sql_lineage')
    kwargs = dict(transport=httpx.MockTransport(provider), authorize=authorize,
                  expected_hash=item['content_hash'])
    if same_recipient:
        with pytest.raises(AgentError, match='Fallback not authorized'):
            assist_task(*args, **kwargs)
        assert authorized == ['test-profile', 'fallback']
    else:
        result = assist_task(*args, **kwargs)
        assert result['outcome'] == 'quarantined' and authorized == ['test-profile']
    assert len(calls) == 1
