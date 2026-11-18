import httpx
from test_ai_resumable_files import configured, empty_provider

from dataforge.ai_analysis_models import (
    AnalysisRequest,
)
from dataforge.analysis_service import run_analysis
from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


def test_selected_ai_rebuild_preserves_unselected_published_files(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('selected build')
    configured(store, w)
    Importer(store, w).files([('a.sql', b'create table first as select id from raw.a;'),
                              ('b.sql', b'create table second as select id from raw.b;')], {'.sql'})
    analyze(store, w)
    selected = next(m['file_id'] for m in store.files(w) if m['relative_path'] == 'a.sql')
    result = run_analysis(store, w, AnalysisRequest(mode='ai', file_ids=[selected]),
                          transport=httpx.MockTransport(empty_provider([])))
    assert result.status == 'committed', result.reasons
    assert len(store.edges(w)) == 1
    assert {r['name'] for r in store.assets(w)} >= {'raw.b', 'second'}
    store.close()


def test_run_time_ceiling_survives_resume(tmp_path, monkeypatch):
    store = Store(tmp_path)
    w = store.create_workspace('time ceiling')
    configured(store, w)
    Importer(store, w).files([('a.sql', b'select 1;')], {'.sql'})
    clock, seen = [0.], []
    monkeypatch.setattr('dataforge.analysis_service.monotonic', lambda: clock[0], raising=False)
    normal = empty_provider(seen)
    def slow(request):
        clock[0] = 31.
        return normal(request)
    result = run_analysis(store, w, AnalysisRequest(mode='ai', max_seconds=30), transport=httpx.MockTransport(slow))
    assert result.status == 'awaiting_continuation'
    assert result.reasons == ['run_time_ceiling_reached']
    resumed = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=result.run_id, retry_unknown=True),
                           transport=httpx.MockTransport(slow))
    assert resumed.reasons == ['run_time_ceiling_reached']
    assert len(seen) == 1
    store.close()


def test_unknown_completion_supersession_is_not_saved_as_completed(tmp_path, monkeypatch):
    import json

    from dataforge.ai_analysis_store import load_file_parts
    store = Store(tmp_path)
    w = store.create_workspace('supersession')
    configured(store, w)
    Importer(store, w).files([('consumer.sas', b'%load;'), ('definition.sas', b'opaque load;')], {'.sas'})
    poisoned = [True]
    stopped = [False]
    def stop(seconds, check):
        stopped[0] = True
        check()
    monkeypatch.setattr('dataforge.analysis_service.recovery_wait', stop)
    def provider(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        items = []
        for item in ctx['items']:
            part = item['part']
            ref = {k: part[k] for k in ('file_id', 'content_hash', 'start_offset', 'end_offset')}
            result = {'part_id': part['part_id']}
            if item['path'] == 'definition.sas':
                result['definitions'] = [{'entry_id': 'load', 'symbol': 'load', 'kind': 'macro', 'source_kind': 'sas',
                    'origin': 'ai_inferred', 'evidence': [ref]}]
            elif part['work_kind'] == 'extraction':
                result['missing_context'] = [{'symbol': 'load', 'kind': 'macro'}]
            elif poisoned[0]:
                result['superseded_fact_ids'] = ['bogus']
            items.append(result)
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'items': items})}}]})
    first = run_analysis(store, w, AnalysisRequest(mode='ai'), cancelled=lambda: stopped[0], transport=httpx.MockTransport(provider))
    assert first.status == 'cancelled'
    initial = load_file_parts(store, w, first.run_id)
    assert len(initial) == 2 and all(p.work_kind == 'extraction' for p, _ in initial)
    assert any(r.definitions for _, r in initial)
    assert not store.rows('SELECT * FROM analysis_runs')
    poisoned[0] = False
    stopped[0] = False
    monkeypatch.setattr('dataforge.analysis_service.time', lambda: 1e12)
    resumed = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id), transport=httpx.MockTransport(provider))
    assert resumed.status == 'committed', resumed.reasons
    assert all(record in load_file_parts(store, w, first.run_id) for record in initial)
    store.close()
