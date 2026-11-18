import json
import threading

import httpx
import pytest
from test_ai_extraction_recovery import envelope, setup_run

from dataforge.agent.jobs import Jobs
from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.analysis_service import run_analysis


def test_blocked_provider_exposes_durable_live_work_and_cancel(tmp_path):
    from dataforge.agent.contracts import AgentError
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
        assert all(file['path'].endswith('.sql') for file in snapshot['current']['files'])
        assert snapshot['activity'][-1]['kind'] == 'dispatch'
        with pytest.raises(AgentError):
            jobs.cancel(job['job_id'], 'other')
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


def test_unexpected_preparation_failure_is_terminal_and_does_not_block_next_run(tmp_path, monkeypatch):
    import dataforge.analysis_service as service
    store, workspace = setup_run(tmp_path, files=1)
    original = service._prepare
    def broken(*args, **kwargs):
        raise RuntimeError('unexpected')
    monkeypatch.setattr(service, '_prepare', broken)
    with pytest.raises(RuntimeError):
        run_analysis(store, workspace, AnalysisRequest(mode='ai'))
    assert store.rows('SELECT status FROM ai_analysis_runs')[0]['status'] == 'failed'
    monkeypatch.setattr(service, '_prepare', original)
    result = run_analysis(store, workspace, AnalysisRequest(mode='ai'),
        transport=httpx.MockTransport(lambda request: httpx.Response(400)))
    assert 'analysis_already_active' not in result.reasons
    store.close()
