from pathlib import Path

from streamlit.testing.v1 import AppTest

from dataforge.ingestion import Importer
from ui.common import get_store


def test_ai_controls_preview_offline_and_block_without_profile(tmp_path, monkeypatch):
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    store = get_store(str(tmp_path))
    workspace = store.create_workspace('AI UI')
    Importer(store, workspace).files([('q.sql', b'create table mart.x as select id from raw.a;')], {'.sql'})
    monkeypatch.setattr('dataforge.analysis_service.invoke_analysis_unit', lambda *a: (_ for _ in ()).throw(
        AssertionError('UI render sent AI')))
    view = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    view.switch_page('ui/pages/analysis.py').run()
    assert not view.exception
    checkbox = next(c for c in view.checkbox if c.label == 'Use AI for analysis')
    assert checkbox.value is False
    checkbox.check().run()
    assert not view.exception
    assert next(c for c in view.checkbox if c.label == 'Compare with parser').value is True
    assert next(b for b in view.button if b.label == 'Analyze with AI + parser').disabled
    assert not store.runs(workspace)
    import streamlit as st
    st.cache_resource.clear()


def test_completed_worker_refreshes_the_whole_report_once(tmp_path, monkeypatch):
    from dataforge.ai_analysis_store import save_run
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    store = get_store(str(tmp_path))
    w = store.create_workspace('Completed UI')
    Importer(store, w).files([('q.sql', b'select id from raw.a;')], {'.sql'})
    save_run(store, w, 'finished', mode='hybrid', status='committed',
        summary={'counts': {'requests': 1, 'accepted': 3}, 'usage_known': False})
    save_run(store, w, 'older', mode='hybrid', status='committed', summary={'counts': {}})

    class CompletedJobs:
        def read(self, *args):
            return {'status': 'completed', 'progress': 1, 'stage': 'Publication complete',
                    'result': {'status': 'committed', 'run_id': 'finished'}}

    monkeypatch.setattr('ui.analysis_ai.analysis_jobs', lambda *args: CompletedJobs())
    view = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    view.session_state['ai_analysis_job_' + w] = 'job'
    view.session_state['ai_report_choice_' + w] = 'older'
    view.switch_page('ui/pages/analysis.py').run()
    assert not view.exception
    assert view.session_state['ai_analysis_refreshed_' + w] == 'job'
    assert view.session_state['ai_report_choice_' + w] == 'finished'
    assert view.get('progress')[0].proto.value == 100
    assert any('Requests: 1' in text.value and 'accepted: 3' in text.value for text in view.markdown)
    import streamlit as st
    st.cache_resource.clear()


def test_pending_worker_elapsed_advances_and_stops_on_completion(tmp_path, monkeypatch):
    import ui.analysis_ai as ai
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    store = get_store(str(tmp_path))
    w = store.create_workspace('Elapsed UI')
    Importer(store, w).files([('q.sql', b'select 1;')], {'.sql'})
    now = [1165.0]
    monkeypatch.setattr(ai, 'time', lambda: now[0])
    record = {'status': 'running', 'progress': .1, 'stage': 'Waiting for AI extraction response',
              'created_at': 900.0, 'started_at': 1000.0, 'stage_started_at': 1100.0}
    class PendingJobs:
        def read(self, *args):
            return record
    monkeypatch.setattr(ai, 'analysis_jobs', lambda *args: PendingJobs())
    view = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    view.session_state['ai_analysis_job_' + w] = 'job'
    view.switch_page('ui/pages/analysis.py').run()
    assert not view.exception
    assert any('Elapsed: 0:02:45' in c.value and 'Waiting: 0:01:05' in c.value for c in view.caption)
    now[0] += 30
    view.run()
    assert any('Elapsed: 0:03:15' in c.value and 'Waiting: 0:01:35' in c.value for c in view.caption)
    record.update(status='completed', finished_at=1200.0, result={'status': 'committed'})
    now[0] = 9999
    view.run()
    assert not view.exception
    assert any('Elapsed: 0:03:20' in c.value and 'Waiting:' not in c.value for c in view.caption)
    import streamlit as st
    st.cache_resource.clear()


def test_budget_defaults_are_automatic_editable_and_resettable(tmp_path, monkeypatch):
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    store = get_store(str(tmp_path))
    w = store.create_workspace('Automatic UI')
    Importer(store, w).files([('q.sql', b'select 1; select 2;')], {'.sql'})
    from dataforge.llm import Profile
    profile = Profile(provider='Ollama', base_url='http://localhost:11434', model='m', retries=0)
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', w, 'm', profile.model_dump_json()])
    store.set_setting(w, 'default_profile', 'p')
    view = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    view.switch_page('ui/pages/analysis.py').run()
    next(c for c in view.checkbox if c.label == 'Use AI for analysis').check().run()
    assert not view.exception
    attempts = next(n for n in view.number_input if n.label == 'Maximum provider attempts')
    assert attempts.value == 2
    attempts.set_value(7).run()
    next(c for c in view.checkbox if c.label == 'Additional AI review').check().run()
    assert next(n for n in view.number_input if n.label == 'Maximum provider attempts').value == 7
    view.switch_page('ui/pages/dashboard.py').run()
    view.switch_page('ui/pages/analysis.py').run()
    next(c for c in view.checkbox if c.label == 'Use AI for analysis').check().run()
    assert next(n for n in view.number_input if n.label == 'Maximum provider attempts').value == 7
    next(c for c in view.checkbox if c.label == 'Additional AI review').check().run()
    next(b for b in view.button if b.label == 'Reset AI budgets to automatic').click().run()
    assert not view.exception
    assert next(n for n in view.number_input if n.label == 'Maximum provider attempts').value == 4
    import streamlit as st
    st.cache_resource.clear()


def test_calculated_context_action_updates_only_context_allowances(tmp_path, monkeypatch):
    import json

    from dataforge.llm import Profile
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    store = get_store(str(tmp_path))
    w = store.create_workspace('Calculated context')
    Importer(store, w).files([('q.sql', b'select 1;')], {'.sql'})
    profile = Profile(provider='Ollama', base_url='http://localhost:11434', model='m', context_chars=500)
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', w, 'm', profile.model_dump_json()])
    store.set_setting(w, 'default_profile', 'p')
    view = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    view.switch_page('ui/pages/analysis.py').run()
    next(c for c in view.checkbox if c.label == 'Use AI for analysis').check().run()
    assert next(b for b in view.button if b.label == 'Analyze with AI + parser').disabled
    next(b for b in view.button if b.label.startswith('Apply calculated context allowance')).click().run()
    assert not view.exception
    assert not next(b for b in view.button if b.label == 'Analyze with AI + parser').disabled
    saved = json.loads(store.rows("SELECT config FROM llm_profiles WHERE profile_id='p'")[0]['config'])
    assert saved['context_chars'] > 500 and saved['max_tokens'] == profile.max_tokens
    for key in ('external_llm', 'allow_full_source', 'llm_history'):
        assert store.setting(w, key, False) is False
    import streamlit as st
    st.cache_resource.clear()


def test_continue_keeps_saved_custom_limits_until_explicit_reset(tmp_path, monkeypatch):
    from dataforge.ai_analysis_models import AnalysisRequest
    from dataforge.ai_analysis_store import save_run
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    store = get_store(str(tmp_path))
    w = store.create_workspace('Continue custom budget')
    Importer(store, w).files([('q.sql', b'select 1;')], {'.sql'})
    saved = AnalysisRequest(mode='hybrid', max_provider_attempts=7)
    save_run(store, w, 'pending', mode='hybrid', status='awaiting_continuation', summary={'request': saved.model_dump()})
    seen = []
    monkeypatch.setattr('ui.analysis_ai.start', lambda s,w,request: seen.append(request))
    view = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    view.switch_page('ui/pages/analysis.py').run()
    next(b for b in view.button if b.label == 'Continue AI analysis').click().run()
    assert not view.exception
    assert seen[0].max_provider_attempts == 7
    import streamlit as st
    st.cache_resource.clear()
