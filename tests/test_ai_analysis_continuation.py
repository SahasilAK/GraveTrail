
from dataforge.ai_analysis_models import AnalysisRequest, Coverage, ProjectLineageResponse, UnitAttemptResult
from dataforge.analysis_service import run_analysis
from dataforge.ingestion import Importer
from dataforge.llm import Profile
from dataforge.store import Store


def test_bounded_execution_resumes_completed_and_partial_units_without_repeating_calls(tmp_path, monkeypatch):
    store = Store(tmp_path)
    w = store.create_workspace('continuation')
    Importer(store, w).files([('many.sql', b'select 1; select 2; select 3;')], {'.sql'})
    p = Profile(provider='Ollama', base_url='http://localhost:11434', model='m', retries=0, context_chars=100000)
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', w, 'm', p.model_dump_json()])
    store.set_setting(w, 'default_profile', 'p')
    store.set_setting(w, 'max_context_chars', 100000)
    calls = []
    checkpoint_writes = []
    from dataforge.analysis_service import save_validation_checkpoint
    def checkpoint(*args, **kwargs):
        checkpoint_writes.append(args[3].unit_id)
        return save_validation_checkpoint(*args, **kwargs)
    monkeypatch.setattr('dataforge.analysis_service.save_validation_checkpoint', checkpoint)
    def extract(store, workspace, unit, task, execution):
        calls.append(unit.unit_id)
        execution.before_attempt(p)
        return UnitAttemptResult(unit_id=unit.unit_id, task=task,
            result=ProjectLineageResponse(unit_id=unit.unit_id, coverage=Coverage(status='partial')))
    monkeypatch.setattr('dataforge.analysis_service.invoke_analysis_unit', extract)
    result = run_analysis(store, w, AnalysisRequest(mode='hybrid', auto_continue=False, max_provider_attempts=1))
    assert result.status == 'awaiting_continuation' and len(calls) == 1
    assert not store.rows('SELECT * FROM analysis_runs')
    run_id = result.run_id
    store.close()
    store = Store(tmp_path)
    for remaining in (1, 0):
        result = run_analysis(store, w, AnalysisRequest(mode='hybrid', auto_continue=False, resume_run_id=run_id, max_provider_attempts=1))
        assert result.status == ('committed' if remaining == 0 else 'awaiting_continuation'), result.reasons
    assert len(calls) == 3 and len(set(calls)) == 3
    assert len(checkpoint_writes) == 3
    assert result.counts['processed'] == 3 and result.counts['requests'] == 3
    store.close()


def test_resume_rejects_changed_configuration_and_preserves_checkpoint(tmp_path, monkeypatch):
    # The complete lifecycle test above exercises reopen; use its setup for the stale boundary.
    store = Store(tmp_path)
    w = store.create_workspace('stale')
    Importer(store, w).files([('q.sql', b'select 1; select 2;')], {'.sql'})
    p = Profile(provider='Ollama', base_url='http://localhost:11434', model='m', retries=0, context_chars=100000)
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', w, 'm', p.model_dump_json()])
    store.set_setting(w, 'default_profile', 'p')
    store.set_setting(w, 'max_context_chars', 100000)
    monkeypatch.setattr('dataforge.analysis_service.invoke_analysis_unit', lambda s,w,u,t,e:
        UnitAttemptResult(unit_id=u.unit_id, task=t, result=ProjectLineageResponse(unit_id=u.unit_id)))
    first = run_analysis(store, w, AnalysisRequest(mode='hybrid', auto_continue=False, max_provider_attempts=1))
    store.set_setting(w, 'case_sensitive', True)
    result = run_analysis(store, w, AnalysisRequest(mode='hybrid', auto_continue=False, resume_run_id=first.run_id))
    assert result.status == 'stale' and not store.rows('SELECT * FROM analysis_runs')
    store.close()


def test_deadline_between_extraction_and_review_resumes_only_missing_review(tmp_path, monkeypatch):
    from dataforge.ai_analysis_models import (
        DerivationCandidate,
        DerivationInput,
        EvidenceCitation,
        LineageReviewResponse,
    )
    store = Store(tmp_path)
    w = store.create_workspace('review checkpoint')
    Importer(store, w).files([('q.sql', b'UPDATE b SET x=a.y FROM a;')], {'.sql'})
    p = Profile(provider='Ollama', base_url='http://localhost:11434', model='m', retries=0, context_chars=100000)
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', w, 'm', p.model_dump_json()])
    store.set_setting(w, 'default_profile', 'p')
    store.set_setting(w, 'max_context_chars', 100000)
    calls = []
    deadline = [True]
    def extract(store, workspace, unit, task, execution):
        calls.append(task)
        if task == 'lineage_review' and deadline[0]:
            calls.pop()
            raise TimeoutError('deadline_exceeded')
        execution.before_attempt(p)
        evidence = EvidenceCitation.from_unit(unit)
        if task == 'project_lineage':
            response = ProjectLineageResponse(unit_id=unit.unit_id, coverage=Coverage(status='complete'),
                derivations=[DerivationCandidate(target_table='b', target_column='x', expression='a.y',
                    category='direct', inputs=[DerivationInput(table='a', column='y')], evidence=evidence)])
        else:
            response = LineageReviewResponse(decisions=[{'candidate_id': c['candidate_id'], 'decision': 'supported',
                'evidence': [evidence.model_dump()]} for c in execution.review_candidates])
        return UnitAttemptResult(unit_id=unit.unit_id, task=task, result=response)
    monkeypatch.setattr('dataforge.analysis_service.invoke_analysis_unit', extract)
    first = run_analysis(store, w, AnalysisRequest(mode='hybrid', auto_continue=False, additional_ai_review=True))
    assert first.status == 'awaiting_continuation' and calls == ['project_lineage']
    deadline[0] = False
    resumed = run_analysis(store, w, AnalysisRequest(mode='hybrid', auto_continue=False, resume_run_id=first.run_id, max_provider_attempts=1))
    assert resumed.status == 'committed', resumed.reasons
    assert calls == ['project_lineage', 'lineage_review'] and resumed.counts['requests'] == 2
    store.close()


def test_unknown_request_requires_explicit_retry_and_does_not_restart_on_open(tmp_path, monkeypatch):
    store = Store(tmp_path)
    w = store.create_workspace('unknown')
    Importer(store, w).files([('q.sql', b'select 1;')], {'.sql'})
    p = Profile(provider='Ollama', base_url='http://localhost:11434', model='m', retries=0, context_chars=100000)
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', w, 'm', p.model_dump_json()])
    store.set_setting(w, 'default_profile', 'p')
    store.set_setting(w, 'max_context_chars', 100000)
    calls = []
    def lost(s, w, u, t, e):
        e.before_attempt(p)
        calls.append(t)
        raise TimeoutError('lost response')
    monkeypatch.setattr('dataforge.analysis_service.invoke_analysis_unit', lost)
    first = run_analysis(store, w, AnalysisRequest(mode='hybrid', auto_continue=False))
    assert first.status == 'awaiting_continuation' and len(calls) == 1
    store.close()
    store = Store(tmp_path)
    resumed = run_analysis(store, w, AnalysisRequest(mode='hybrid', auto_continue=False, resume_run_id=first.run_id))
    assert resumed.reasons == ['unknown_inflight_request_requires_explicit_retry'] and len(calls) == 1
    store.close()


def test_zero_cost_prefix_does_not_hide_an_unaffordable_next_unit(tmp_path, monkeypatch):
    store = Store(tmp_path)
    w = store.create_workspace('no zero-work continuation')
    Importer(store, w).files([('q.sql', b'select 1; select 2;')], {'.sql'})
    p = Profile(provider='Ollama', base_url='http://localhost:11434', model='m', retries=1, context_chars=100000)
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', w, 'm', p.model_dump_json()])
    store.set_setting(w, 'default_profile', 'p')
    store.set_setting(w, 'max_context_chars', 100000)
    monkeypatch.setattr('dataforge.analysis_service.invoke_analysis_unit', lambda s,w,u,t,e:
        UnitAttemptResult(unit_id=u.unit_id, task=t, result=ProjectLineageResponse(unit_id=u.unit_id)))
    first = run_analysis(store, w, AnalysisRequest(mode='hybrid', auto_continue=False, max_provider_attempts=2))
    assert first.status == 'awaiting_continuation'
    resumed = run_analysis(store, w, AnalysisRequest(mode='hybrid', auto_continue=False, resume_run_id=first.run_id, max_provider_attempts=1))
    assert resumed.status == 'blocked' and any('single_unit' in reason for reason in resumed.reasons)
    # An insufficient proposed execution must keep the paused run resumable.
    assert store.rows('SELECT status FROM ai_analysis_runs WHERE run_id=?', [first.run_id])[0]['status'] == 'awaiting_continuation'
    store.close()
