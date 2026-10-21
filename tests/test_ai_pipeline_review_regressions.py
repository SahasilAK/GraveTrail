import json

import httpx
import pytest

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.analysis_service import run_analysis
from dataforge.connections import RuntimeConnections, connection_scope
from dataforge.ingestion import Importer
from dataforge.llm import Adapter, Profile
from dataforge.store import Store
from tests.test_ai_full_build import configured


def test_revoked_credential_is_not_sent_after_admission_wait():
    manager = RuntimeConnections()
    manager.register('DATAFORGE_REVOKED_KEY', 'synthetic-secret')
    profile = Profile(provider='OpenAI compatible', base_url='http://localhost:1234', model='m',
                      key_env='DATAFORGE_REVOKED_KEY', retries=0)
    sent = []
    def revoke(_):
        manager.clear('DATAFORGE_REVOKED_KEY')
        return 1
    def provider(r):
        sent.append(r)
        return httpx.Response(200, json={'choices': [{'message': {'content': '{}'}}]})
    with connection_scope(manager), Adapter(profile, httpx.MockTransport(provider), before_attempt=revoke) as adapter:
        with pytest.raises(ValueError, match='Credential'):
            adapter.complete('instructions', 'source')
    assert not sent


def test_partial_http_200_stream_stays_unknown(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('lost stream')
    configured(store, w)
    Importer(store, w).files([('a.sql', b'select 1;')], {'.sql'})
    class LostStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b'{"choices":'
            raise httpx.ReadError('synthetic stream loss')
    result = run_analysis(store, w, AnalysisRequest(mode='ai', max_parallel_requests=2),
        transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=LostStream())))
    assert result.status == 'awaiting_continuation'
    assert result.reasons == ['unknown_inflight_request_requires_explicit_retry']
    assert store.rows('SELECT status FROM ai_analysis_attempts')[0]['status'] == 'unknown'
    store.close()


def test_resume_reconciles_spend_from_attempt_ledger_after_summary_write_loss(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('ledger recovery')
    configured(store, w)
    Importer(store, w).files([('a.sql', b'select 1; select 2; select 3;')], {'.sql'})
    sent = []
    def provider(r):
        sent.append(1)
        text = json.loads(r.content)['messages'][1]['content']
        context = json.loads(text[text.index('{'):])
        items = context.get('items', [context])
        results = [{'unit_id': c['unit']['unit_id'], 'coverage': {'status': 'partial'}} for c in items]
        payload = {'items': results} if 'items' in context else results[0]
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(payload)}}]})
    transport = httpx.MockTransport(provider)
    first = run_analysis(store, w, AnalysisRequest(mode='ai', max_files_per_request=2,
        max_provider_attempts=1, project_max_provider_attempts=1, auto_continue=False), transport=transport)
    assert first.status == 'awaiting_continuation' and len(sent) == 1
    summary = json.loads(store.rows('SELECT summary FROM ai_analysis_runs WHERE run_id=?', [first.run_id])[0]['summary'])
    summary['counts']['requests'] = summary['counts']['reserved_output_tokens'] = 0
    store.execute('UPDATE ai_analysis_runs SET summary=? WHERE run_id=?', [json.dumps(summary), first.run_id])
    store.close()
    store = Store(tmp_path)
    resumed = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id), transport=transport)
    assert len(sent) == 1
    assert resumed.status == 'awaiting_continuation'
    assert resumed.counts['requests'] == 1 and resumed.counts['reserved_output_tokens'] >= 8192
    store.close()
