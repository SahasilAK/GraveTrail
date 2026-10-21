from dataforge.ai_analysis_models import AnalysisRequest, Coverage, ProjectLineageResponse, UnitAttemptResult
from dataforge.analysis_service import run_analysis
from dataforge.ingestion import Importer
from dataforge.llm import Profile
from dataforge.store import Store


def test_one_start_rolls_windows_and_obeys_lifetime_limit(tmp_path, monkeypatch):
    store = Store(tmp_path)
    w = store.create_workspace('rollover')
    Importer(store, w).files([('q.sql', b'select 1; select 2; select 3;')], {'.sql'})
    p = Profile(provider='Ollama', base_url='http://localhost:11434', model='m', retries=0, context_chars=100000)
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', w, 'm', p.model_dump_json()])
    store.set_setting(w, 'default_profile', 'p')
    store.set_setting(w, 'max_context_chars', 100000)
    calls = []
    def extract(s, w, u, t, e):
        e.before_attempt(p)
        calls.append(u.unit_id)
        return UnitAttemptResult(unit_id=u.unit_id, task=t,
            result=ProjectLineageResponse(unit_id=u.unit_id, coverage=Coverage(status='partial')))
    monkeypatch.setattr('dataforge.analysis_service.invoke_analysis_unit', extract)
    first = run_analysis(store, w, AnalysisRequest(mode='ai', max_provider_attempts=1))
    assert first.status == 'committed', first.reasons
    assert first.counts['requests'] == 3 and len(set(calls)) == 3
    calls.clear()
    second = run_analysis(store, w, AnalysisRequest(mode='ai', refresh_ai=True,
        max_provider_attempts=1, project_max_provider_attempts=2))
    assert second.status == 'awaiting_continuation'
    assert second.reasons == ['project_allowance_reached']
    assert len(calls) == 2
    store.close()
