import json

import httpx
from test_ai_resumable_files import configured, empty_provider
from test_ai_token_budget import model

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.analysis_service import analysis_report, run_analysis
from dataforge.ingestion import Importer
from dataforge.store import Store


def setup_run(tmp_path, *, unknown=1, retries=2):
    store = Store(tmp_path)
    workspace = store.create_workspace('gateway')
    profile = model().model_copy(update={'unknown_retries': unknown, 'retries': retries})
    configured(store, workspace, profile)
    Importer(store, workspace).files([('a.sql', b'select 1;')], {'.sql'})
    return store, workspace


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
    summary = analysis_report(store, w, first.run_id)['summary']
    summary['counts']['requests'] = summary['counts']['reserved_output_tokens'] = 0
    store.execute('UPDATE ai_analysis_runs SET summary=? WHERE run_id=?', [json.dumps(summary), first.run_id])
    store.close()
    store = Store(tmp_path)
    second = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id, retry_unknown=True),
        transport=httpx.MockTransport(provider))
    assert second.status == 'awaiting_continuation'
    assert len(calls) == 3
    assert second.counts['requests'] == 3
    assert second.counts['reserved_output_tokens'] == 24000
    assert not second.usage_known
    assert analysis_report(store, w, first.run_id)['summary']['last_failure']['allowance_exhausted']
    store.close()


def test_permanent_auth_failure_never_retried(tmp_path):
    store, w = setup_run(tmp_path)
    seen = []
    def provider(request):
        seen.append(1)
        return httpx.Response(401)
    result = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider))
    assert result.status != 'committed' and len(seen) == 1
    detail = json.loads(store.rows('SELECT details FROM ai_analysis_attempts')[0]['details'])
    assert detail['failure_category'] == 'authentication' and not detail['retry_scheduled']
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
