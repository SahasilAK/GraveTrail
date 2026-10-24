import json

import httpx
import pytest
from test_ai_resumable_files import configured, empty_provider
from test_ai_token_budget import model

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_pipeline_store import recover_pipeline
from dataforge.analysis_service import analysis_report, run_analysis
from dataforge.ingestion import Importer
from dataforge.llm import Adapter, Profile
from dataforge.store import Store


def setup_run(tmp_path, *, unknown=1, retries=2):
    store = Store(tmp_path)
    workspace = store.create_workspace('gateway')
    profile = model().model_copy(update={'unknown_retries': unknown, 'retries': retries})
    configured(store, workspace, profile)
    Importer(store, workspace).files([('a.sql', b'select 1;')], {'.sql'})
    return store, workspace


def test_legacy_timeout_is_read_fallback_and_unknown_recovery_stays_opt_in():
    profile = Profile(provider='OmniRoute', base_url='http://localhost:20128/v1', model='m', timeout=83)
    assert profile.unknown_retries == 0
    with Adapter(profile) as adapter:
        assert adapter.client.timeout.read == 83
        assert adapter.client.timeout.connect == 5


@pytest.mark.parametrize('failure', [httpx.ConnectTimeout, httpx.PoolTimeout, httpx.ConnectError,
                                     httpx.ReadTimeout, httpx.ReadError, httpx.RemoteProtocolError,
                                     httpx.WriteTimeout, httpx.ProxyError])
def test_failure_retry_keeps_each_attempt_and_reservation(tmp_path, failure):
    store, w = setup_run(tmp_path)
    seen, calls = [], []
    good = empty_provider(seen)
    def provider(request):
        calls.append(1)
        if len(calls) == 1:
            raise failure('Authorization: Bearer DO_NOT_PERSIST private source select 1')
        return good(request)
    result = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider))
    assert result.status == 'committed', result.reasons
    attempts = store.rows('SELECT status,details,reserved_output FROM ai_analysis_attempts')
    safe = failure in {httpx.ConnectTimeout, httpx.PoolTimeout, httpx.ConnectError}
    assert [r['status'] for r in attempts] == ['known_failure' if safe else 'unknown', 'received']
    assert result.counts['requests'] == 2 and result.counts['reserved_output_tokens'] == 16000
    assert result.usage_known is safe
    detail = json.loads(attempts[0]['details'])
    assert detail['failure_category'] == ('pre_send' if safe else 'transport_unknown')
    assert detail['attempt_number'] == 1 and detail['retry_scheduled']
    assert detail['elapsed_seconds'] >= 0 and detail['timeouts']['read'] == 30
    assert detail['transport_error'] == failure.__name__
    assert 'DO_NOT_PERSIST' not in json.dumps(attempts)
    assert not recover_pipeline(store, w, result.run_id)['unknown']
    assert len(store.rows('SELECT * FROM analysis_runs')) == 1
    store.close()


def test_http_and_unknown_passes_share_explicit_run_budget_across_restart(tmp_path):
    store, w = setup_run(tmp_path, unknown=2)
    calls = []
    def provider(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503)
        raise httpx.ReadTimeout('lost response')
    first = run_analysis(store, w, AnalysisRequest(mode='ai', max_provider_attempts=3), transport=httpx.MockTransport(provider))
    assert first.status == 'awaiting_continuation'
    assert len(calls) == 3
    assert first.reasons == ['run_attempt_ceiling_reached']
    assert [r['status'] for r in store.rows('SELECT status FROM ai_analysis_attempts')] == ['known_failure', 'unknown', 'unknown']
    store.close()
    store = Store(tmp_path)
    second = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id), transport=httpx.MockTransport(provider))
    assert second.status == 'awaiting_continuation'
    assert len(calls) == 3
    assert second.counts['requests'] == 3
    assert not second.usage_known
    assert analysis_report(store, w, first.run_id)['summary']['last_failure']['allowance_exhausted']
    store.close()


@pytest.mark.parametrize('unknown', [0, 1])
def test_permanent_auth_failure_never_retried(tmp_path, unknown):
    store, w = setup_run(tmp_path, unknown=unknown)
    seen = []
    def provider(request):
        seen.append(1)
        return httpx.Response(401)
    result = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider))
    assert result.status != 'committed' and len(seen) == 1
    detail = json.loads(store.rows('SELECT details FROM ai_analysis_attempts')[0]['details'])
    assert detail['failure_category'] == 'authentication' and not detail['retry_scheduled']
    store.close()


def test_disabled_unknown_retry_requires_manual_ack_and_preserves_unknown_ledger(tmp_path):
    store, w = setup_run(tmp_path, unknown=0)
    def lost(request):
        raise httpx.ReadTimeout('lost')
    first = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(lost))
    assert first.reasons == ['unknown_inflight_request_requires_explicit_retry']
    seen = []
    blocked = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id),
                           transport=httpx.MockTransport(empty_provider(seen)))
    assert not seen and blocked.status == 'awaiting_continuation'
    done = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id, retry_unknown=True),
                        transport=httpx.MockTransport(empty_provider(seen)))
    assert done.status == 'committed' and not done.usage_known
    assert [a['status'] for a in store.rows('SELECT status FROM ai_analysis_attempts')] == ['unknown', 'received']
    store.close()


@pytest.mark.parametrize('limit', ['attempt', 'tokens'])
def test_retry_does_not_bypass_run_ceiling_after_restart(tmp_path, limit):
    store, w = setup_run(tmp_path)
    calls = []
    def lost(request):
        calls.append(1)
        raise httpx.ReadTimeout('lost')
    request = AnalysisRequest(mode='ai', **({'max_provider_attempts': 1} if limit == 'attempt' else {'max_output_tokens_total': 8000}))
    first = run_analysis(store, w, request, transport=httpx.MockTransport(lost))
    assert len(calls) == 1 and first.status == 'awaiting_continuation'
    store.close()
    store = Store(tmp_path)
    second = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id, retry_unknown=True),
                           transport=httpx.MockTransport(lost))
    assert len(calls) == 1 and second.counts['reserved_output_tokens'] == 8000
    store.close()


@pytest.mark.parametrize('stop', ['cancel', 'deadline'])
def test_no_retry_after_cancel_or_run_limit_during_backoff(tmp_path, monkeypatch, stop):
    store, w = setup_run(tmp_path)
    calls, clock, cancelled = [], [0.], [False]
    monkeypatch.setattr('dataforge.analysis_service.monotonic', lambda: clock[0])
    def advance(seconds):
        clock[0] = 31.
        cancelled[0] = True
    monkeypatch.setattr('dataforge.llm.time.sleep', advance)
    def lost(request):
        calls.append(1)
        raise httpx.ReadTimeout('lost')
    result = run_analysis(store, w, AnalysisRequest(mode='ai', max_seconds=30 if stop == 'deadline' else None),
        cancelled=(lambda: cancelled[0]) if stop == 'cancel' else None, transport=httpx.MockTransport(lost))
    assert len(calls) == 1
    assert result.status == ('cancelled' if stop == 'cancel' else 'awaiting_continuation')
    assert store.rows('SELECT status FROM ai_analysis_attempts')[0]['status'] == 'unknown'
    store.close()


def test_completed_batch_is_not_resent_and_publication_happens_once(tmp_path):
    store, w = setup_run(tmp_path)
    Importer(store, w).files([('a.sql', b'select 1;' + b' ' * 9000), ('b.sql', b'select 2;' + b' ' * 9000)], {'.sql'})
    calls, seen = [], []
    good = empty_provider(seen)
    def provider(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        calls.append(ctx['items'][0]['part']['part_id'])
        if len(calls) == 2:
            raise httpx.ReadError('lost')
        return good(request)
    result = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider))
    assert result.status == 'committed', result.reasons
    assert len(calls) == 3 and calls[0] != calls[1] == calls[2]
    assert len(seen) == len(set(seen)) == 2
    assert len(store.rows('SELECT * FROM analysis_runs')) == 1
    store.close()


def test_recovery_messages_do_not_claim_upstream_failover():
    from dataforge.analysis_service import recovery_message
    text = recovery_message({'last_failure': {'failure_category': 'transport_unknown', 'retry_scheduled': True,
                            'batch_number': 3, 'cycle_attempt': 1, 'attempt_limit': 3}})
    assert 'before a complete response' in text and 'batch 3, attempt 2 of 3' in text
    assert 'switching' not in text and 'unknown_inflight' not in text


def test_legacy_checkpoint_cannot_erase_processed_unknown_usage(tmp_path, monkeypatch):
    import dataforge.analysis_service as service
    store, w = setup_run(tmp_path)
    seen = []
    good = empty_provider(seen)
    first_call = [True]
    def provider(request):
        if first_call[0]:
            first_call[0] = False
            raise httpx.ReadError('lost')
        return good(request)
    original = service.plan_file_consolidation
    monkeypatch.setattr(service, 'plan_file_consolidation', lambda *a, **k: (_ for _ in ()).throw(ValueError('interrupted stage')))
    first = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider))
    assert first.status == 'failed' and not first.usage_known
    summary = analysis_report(store, w, first.run_id)['summary']
    summary['usage_known'] = True  # Simulate an older summary checkpoint lagging the durable ledger.
    store.execute('UPDATE ai_analysis_runs SET summary=? WHERE run_id=?', [json.dumps(summary), first.run_id])
    monkeypatch.setattr(service, 'plan_file_consolidation', original)
    store.close()
    store = Store(tmp_path)
    resumed = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id),
        transport=httpx.MockTransport(lambda r: pytest.fail('Completed work resent')))
    assert resumed.status == 'committed' and not resumed.usage_known
    store.close()


@pytest.mark.parametrize('read_wait', [83., .2])
def test_existing_profile_ui_keeps_read_wait_and_unknown_retry_policy(tmp_path, monkeypatch, read_wait):
    from pathlib import Path

    import streamlit as st
    from streamlit.testing.v1 import AppTest

    from ui.common import get_store
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    store = get_store(str(tmp_path))
    w = store.create_workspace('old profile')
    legacy = model().model_dump()
    legacy.update(provider='OmniRoute', timeout=83)
    for key in ('unknown_retries', 'connect_timeout', 'read_timeout'):
        legacy.pop(key, None)
    if read_wait < 1:
        legacy.update(read_timeout=read_wait, connect_timeout=.2)
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['legacy', w, 'old', json.dumps(legacy)])
    view = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    view.switch_page('ui/pages/connections.py').run()
    next(s for s in view.selectbox if s.label == 'Provider profile').select('legacy').run()
    assert next(n for n in view.number_input if n.label == 'Response inactivity timeout (seconds)').value == read_wait
    assert next(n for n in view.number_input if n.label == 'Connection timeout (seconds)').value == (.2 if read_wait < 1 else 5.)
    assert next(n for n in view.number_input if n.label == 'Automatic retries of unknown outcomes').value == 0
    next(b for b in view.button if b.label == 'Save provider profile').click().run()
    assert not view.exception
    saved = json.loads(store.rows('SELECT config FROM llm_profiles WHERE profile_id=?', ['legacy'])[0]['config'])
    assert saved['timeout'] == 83 and saved['read_timeout'] == read_wait and saved['unknown_retries'] == 0
    st.cache_resource.clear()


def test_ui_explains_exhausted_unknown_without_showing_internal_reason(tmp_path, monkeypatch):
    from pathlib import Path

    import streamlit as st
    from streamlit.testing.v1 import AppTest

    from dataforge.ai_analysis_store import save_run
    from ui.common import get_store
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    store = get_store(str(tmp_path))
    w = store.create_workspace('report')
    Importer(store, w).files([('a.sql', b'select 1;')], {'.sql'})
    save_run(store, w, 'paused', mode='ai', status='awaiting_continuation', summary={
        'protocol_version': 5, 'request': AnalysisRequest(mode='ai').model_dump(),
        'reasons': ['unknown_inflight_request_requires_explicit_retry'],
        'retry_policy': {'unknown_retries': 2},
        'last_failure': {'failure_category': 'transport_unknown', 'allowance_exhausted': True, 'retry_scheduled': False}})
    view = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    view.switch_page('ui/pages/analysis.py').run()
    assert not view.exception
    assert any('automatic retry allowance is exhausted' in v.value for v in view.warning)
    assert all('unknown_inflight' not in v.value for v in view.warning)
    assert next(b for b in view.button if b.label == 'Continue AI analysis').disabled
    assert any('unfinished batch' in c.label for c in view.checkbox)
    st.cache_resource.clear()


def test_guard_value_error_cannot_become_item_retry_or_renew_network_budget(tmp_path, monkeypatch):
    import dataforge.analysis_service as service
    store, w = setup_run(tmp_path, unknown=0, retries=0)
    seen, changed = [], [False]
    good = empty_provider(seen)
    original = service._current
    def current(*args, **kwargs):
        if changed[0]:
            changed[0] = False
            raise ValueError('source_or_configuration_changed')
        return original(*args, **kwargs)
    monkeypatch.setattr(service, '_current', current)
    def provider(request):
        response = good(request)
        changed[0] = True
        return response
    result = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider))
    assert result.status == 'stale' and len(seen) == 1
    assert store.rows('SELECT status FROM ai_analysis_attempts')[0]['status'] == 'unknown'
    request = store.rows('SELECT status,details FROM ai_analysis_requests')[0]
    assert request['status'] == 'planned'
    assert 'completed_response_baseline' not in json.loads(request['details'])
    assert not store.rows('SELECT * FROM analysis_runs')
    store.close()


def test_received_but_uncheckpointed_response_consumes_recovery_allowance(tmp_path, monkeypatch):
    import dataforge.analysis_service as service
    store, w = setup_run(tmp_path, unknown=1, retries=2)
    original = service.plan_file_consolidation
    monkeypatch.setattr(service, 'plan_file_consolidation', lambda *a, **k: (_ for _ in ()).throw(ValueError('stopped before publication')))
    first = run_analysis(store, w, AnalysisRequest(mode='ai', max_provider_attempts=2), transport=httpx.MockTransport(empty_provider([])))
    assert first.status == 'failed'
    # Reconstruct a crash window after receipt but before result checkpointing.
    store.execute('DELETE FROM ai_analysis_units WHERE run_id=?', [first.run_id])
    details = json.loads(store.rows('SELECT details FROM ai_analysis_requests')[0]['details'])
    details.pop('completed_response_baseline', None)
    store.execute("UPDATE ai_analysis_requests SET status='planned',details=?", [json.dumps(details)])
    monkeypatch.setattr(service, 'plan_file_consolidation', original)
    store.close()
    calls = []
    def lost(request):
        calls.append(1)
        raise httpx.ReadTimeout('lost recovery')
    store = Store(tmp_path)
    second = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id), transport=httpx.MockTransport(lost))
    assert second.status == 'awaiting_continuation' and not second.usage_known
    assert len(calls) == 1
    third = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id), transport=httpx.MockTransport(lost))
    assert third.status == 'awaiting_continuation' and len(calls) == 1
    assert [r['status'] for r in store.rows('SELECT status FROM ai_analysis_attempts')] == ['received', 'unknown']
    assert third.counts['reserved_output_tokens'] == 16000
    store.close()


def test_invalid_model_item_and_transport_recovery_share_run_spending_budget(tmp_path):
    store, w = setup_run(tmp_path, unknown=2, retries=2)
    calls = []
    def provider(request):
        calls.append(1)
        if len(calls) == 2:
            return httpx.Response(200, json={'choices': [{'message': {'content': '{"items":[]}'}}]})
        raise httpx.ReadTimeout('lost')
    result = run_analysis(store, w, AnalysisRequest(mode='ai', max_provider_attempts=3), transport=httpx.MockTransport(provider))
    assert result.status == 'awaiting_continuation'
    assert len(calls) == 3
    assert result.counts['reserved_output_tokens'] == 24000
    store.close()


def test_wait_until_stopped_preserves_other_timeouts_and_old_profiles():
    profile = Profile(provider='OmniRoute', base_url='http://localhost:20128/v1', model='m',
                      timeout=83, read_timeout=90, wait_until_stopped=True)
    with Adapter(profile, cancelled=lambda: False) as adapter:
        assert adapter._timeouts(12).as_dict() == {'connect': 5, 'read': None, 'write': 83, 'pool': 5}
    with Adapter(profile) as adapter:
        assert adapter._timeouts().read == 90  # Setup/discovery has no Stop control.
    assert Profile.model_validate(profile.model_dump()).wait_until_stopped


def test_read_timeout_message_differs_from_disconnection():
    from dataforge.analysis_service import recovery_message
    summary = {'last_failure': {'failure_category': 'transport_unknown', 'transport_error': 'ReadTimeout'}}
    assert 'app timed out' in recovery_message(summary)
    summary['last_failure']['transport_error'] = 'RemoteProtocolError'
    assert 'connection ended' in recovery_message(summary)
