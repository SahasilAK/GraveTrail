import json
import threading

import httpx
import pytest
from test_ai_extraction_recovery import envelope, setup_run

from dataforge.agent.jobs import Jobs
from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.analysis_service import run_analysis


def test_blocked_provider_exposes_durable_live_work_and_cancel(tmp_path):
    from dataforge.ai_analysis_progress import analysis_progress

    store, workspace = setup_run(tmp_path, files=2)
    entered, release = threading.Event(), threading.Event()
    calls = []

    def provider(request):
        calls.append(json.loads(request.content))
        entered.set()
        assert release.wait(10)
        return envelope([])

    jobs = Jobs(tmp_path)
    try:
        job = jobs.start(workspace, 'ai_analysis', lambda progress, cancelled: run_analysis(
            store, workspace, AnalysisRequest(mode='ai'), progress=progress, cancelled=cancelled,
            transport=httpx.MockTransport(provider)).model_dump(), cancellable=True)
        assert entered.wait(10)
        record = jobs.read(job['job_id'], workspace)
        assert record['run_id']
        snapshot = analysis_progress(store, workspace, record['run_id'])
        assert snapshot['files'] == {'selected': 2, 'completed': 0, 'partial': 0, 'unfinished': 2}
        assert snapshot['parts']['planned'] == 2 and snapshot['parts']['completed'] == 0
        assert snapshot['attempts']['in_flight'] == 1
        assert snapshot['tokens']['actual_input'] is None
        assert snapshot['current']['part_ids'] and snapshot['current']['file_ids']
        assert snapshot['activity'][-1]['kind'] == 'dispatch'
        jobs.cancel(job['job_id'], workspace)
        assert jobs.read(job['job_id'], workspace)['cancel_requested']
        assert len(calls) == 1
        with pytest.raises(ValueError):
            analysis_progress(store, 'other', record['run_id'])
        release.set()
        assert jobs.wait(job['job_id'], workspace, timeout=10)['status'] == 'cancelled'
    finally:
        release.set()
        jobs.close()
        store.close()


def test_progress_is_measured_reopenable_and_does_not_load_sources(tmp_path, monkeypatch):
    from dataforge.ai_analysis_progress import analysis_progress
    from dataforge.store import Store

    store, workspace = setup_run(tmp_path, files=2)
    def provider(request):
        body = json.loads(json.loads(request.content)['messages'][-1]['content'])
        return envelope([{'part_id': item['part']['part_id'], 'coverage': 'no_operations'} for item in body['items']])
    result = run_analysis(store, workspace, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider))
    assert result.status == 'committed'
    monkeypatch.setattr(store, 'snapshot_content', lambda *a: pytest.fail('Progress hydrated source'))
    snapshot = analysis_progress(store, workspace, result.run_id)
    assert snapshot['files'] == {'selected': 2, 'completed': 2, 'partial': 0, 'unfinished': 0}
    assert snapshot['parts']['completed'] == snapshot['parts']['planned'] == 2
    assert snapshot['requests']['processed'] == 1
    assert snapshot['attempts']['received'] == 1
    assert {'response', 'validation', 'persistence', 'publication'} <= {a['kind'] for a in snapshot['activity']}
    store.close()
    store = Store(tmp_path)
    assert analysis_progress(store, workspace, result.run_id) == snapshot
    store.close()


def test_run_identity_and_unknown_totals_are_available_during_preparation(tmp_path, monkeypatch):
    import dataforge.analysis_service as service
    from dataforge.ai_analysis_progress import analysis_progress
    store, workspace = setup_run(tmp_path, files=1)
    def prepare(*args, **kwargs):
        rows = store.rows('SELECT run_id FROM ai_analysis_runs WHERE workspace_id=?', [workspace])
        assert len(rows) == 1
        assert analysis_progress(store, workspace, rows[0]['run_id'])['parts']['planned'] is None
        raise InterruptedError('cancelled')
    monkeypatch.setattr(service, '_prepare', prepare)
    result = run_analysis(store, workspace, AnalysisRequest(mode='ai'))
    assert result.status == 'cancelled'
    assert store.rows('SELECT status FROM ai_analysis_runs')[0]['status'] == 'cancelled'
    store.close()


def test_resume_counts_reuse_before_waiting_and_additional_work(tmp_path):
    from dataforge.ai_analysis_progress import analysis_progress
    store, workspace = setup_run(tmp_path, files=0)
    from dataforge.ai_analysis_store import save_run
    from dataforge.ai_pipeline_store import begin_attempt, finish_attempt, save_request
    save_run(store, workspace, 'r', mode='ai', status='extracting', summary={
        'parts': [{'part_id': 'a', 'file_id': 'f', 'work_kind': 'extraction'}]})
    save_request(store, workspace, 'r', 'q', ['a'])
    ticket = begin_attempt(store, workspace, 'r', 'q', 100)
    finish_attempt(store, workspace, 'r', ticket, 'unknown')
    first = analysis_progress(store, workspace, 'r')
    assert first['attempts']['unknown'] == 1 and first['files']['unfinished'] == 1
    assert first['tokens']['actual_output'] is None
    save_run(store, workspace, 'r', mode='ai', status='consolidating', summary={
        'completion_work': [{'part': {'part_id': 'b', 'file_id': 'f', 'work_kind': 'context_completion'}}],
        'unresolved_work': {'a': {'file_id': 'f'}}})
    later = analysis_progress(store, workspace, 'r')
    assert later['parts']['planned'] == 2 and later['parts']['unresolved'] == 1
    assert later['parts']['remaining'] == 2
    assert later['files']['completed'] == 0
    store.close()
