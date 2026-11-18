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
        before = store.edges(w)
        sent = request_review(store, w, item['diagnostic_id'], item['content_hash'], 1, 1,
                              transport=httpx.MockTransport(provider))
        assert sent['outcome'] == 'quarantined' and sent['budget'] == result['budget']
        assert store.edges(w) == before
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
