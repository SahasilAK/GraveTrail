from pathlib import Path

from streamlit.testing.v1 import AppTest

from dataforge.ingestion import Importer
from ui.common import get_store


def test_ai_controls_preview_offline_and_block_without_profile(tmp_path, monkeypatch):
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    store = get_store(str(tmp_path))
    workspace = store.create_workspace('AI UI')
    Importer(store, workspace).files([('q.sql', b'create table mart.x as select id from raw.a;')], {'.sql'})
    monkeypatch.setattr('dataforge.llm.Adapter.complete', lambda *a: (_ for _ in ()).throw(
        AssertionError('UI render sent AI')))
    view = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    view.switch_page('ui/pages/analysis.py').run()
    assert not view.exception
    checkbox = next(c for c in view.checkbox if c.label == 'Use AI for analysis')
    assert checkbox.value is False
    checkbox.check().run()
    assert not view.exception
    assert not any(c.label in {'Compare with parser', 'Additional AI review'} for c in view.checkbox)
    assert next(b for b in view.button if b.label == 'Analyze with AI').disabled
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


def test_normal_controls_only_expose_one_optional_run_ceiling(tmp_path, monkeypatch):
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    store = get_store(str(tmp_path))
    w = store.create_workspace('Token UI')
    Importer(store, w).files([('q.sql', b'select 1;')], {'.sql'})
    from test_ai_resumable_files import configured
    configured(store, w)
    view = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    view.switch_page('ui/pages/analysis.py').run()
    next(c for c in view.checkbox if c.label == 'Use AI for analysis').check().run()
    assert not view.exception
    assert [n.label for n in view.number_input] == ['Run output token ceiling (optional)']
    assert view.number_input[0].value is None
    view.number_input[0].set_value(16000).run()
    assert not view.exception
    assert not next(b for b in view.button if b.label == 'Analyze with AI').disabled
    import streamlit as st
    st.cache_resource.clear()


def test_legacy_report_stays_readable_but_cannot_resume(tmp_path, monkeypatch):
    from dataforge.ai_analysis_models import AnalysisRequest
    from dataforge.ai_analysis_store import save_run
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    store = get_store(str(tmp_path))
    w = store.create_workspace('Historical UI')
    Importer(store, w).files([('q.sql', b'select 1;')], {'.sql'})
    save_run(store, w, 'old', mode='hybrid', status='awaiting_continuation',
             summary={'request': AnalysisRequest(mode='hybrid').model_dump()})
    view = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    view.switch_page('ui/pages/analysis.py').run()
    assert not view.exception
    assert not any(b.label == 'Continue AI analysis' for b in view.button)
    assert any('incompatible protocol' in i.value for i in view.info)
    import streamlit as st
    st.cache_resource.clear()


def test_analyze_reuses_preview_and_shows_cancellable_worker_before_inventory(tmp_path, monkeypatch):
    import streamlit as st
    from test_ai_resumable_files import configured

    import ui.analysis_ai as ai
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    store = get_store(str(tmp_path))
    w = store.create_workspace('Start UI')
    configured(store, w)
    Importer(store, w).files([('q.sql', b'select 1;')], {'.sql'})
    original = ai.preview_analysis
    previews, cancellations, starts = [], [], []
    record = {'status': 'running', 'progress': .1, 'stage': 'Preparing selected sources'}
    def preview(*args, **kwargs):
        previews.append(1)
        return original(*args, **kwargs)
    class PendingJobs:
        def start(self, *args, **kwargs):
            starts.append(1)
            return {'job_id': 'queued'}
        def read(self, *args):
            return record
        def cancel(self, *args):
            cancellations.append(args)
    monkeypatch.setattr(ai, 'analysis_jobs', lambda *args: PendingJobs())
    monkeypatch.setattr(ai, 'preview_analysis', preview)
    view = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    view.switch_page('ui/pages/analysis.py').run()
    next(c for c in view.checkbox if c.label == 'Use AI for analysis').check().run()
    assert len(previews) == 1
    next(b for b in view.button if b.label == 'Analyze with AI').click().run()
    assert not view.exception and len(starts) == 1
    assert len(previews) == 1, 'Analyze must not repeat the expensive preview'
    assert any(b.label == 'Cancel AI analysis' for b in view.button)
    original_files = store.files
    monkeypatch.setattr(store, 'files', lambda *args: (_ for _ in ()).throw(AssertionError('Worker UI waited on inventory')))
    next(b for b in view.button if b.label == 'Cancel AI analysis').click().run()
    assert not view.exception and cancellations == [('queued', w)]
    monkeypatch.setattr(store, 'files', original_files)
    record.update(status='cancelled', result={'status': 'cancelled'})
    view.run()
    assert not view.exception and len(previews) == 1
    assert next(c for c in view.checkbox if c.label == 'Use AI for analysis').value
    st.cache_resource.clear()


def test_preview_cache_invalidates_for_sources_settings_profile_and_request(tmp_path, monkeypatch):
    import json

    import streamlit as st
    from test_ai_resumable_files import configured

    import ui.analysis_ai as ai
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    store = get_store(str(tmp_path))
    w = store.create_workspace('Preview freshness')
    configured(store, w)
    Importer(store, w).files([('q.sql', b'select 1;')], {'.sql'})
    original, calls = ai.preview_analysis, []
    def preview(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(ai, 'preview_analysis', preview)
    view = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    view.switch_page('ui/pages/analysis.py').run()
    next(c for c in view.checkbox if c.label == 'Use AI for analysis').check().run()
    view.run()
    assert len(calls) == 1
    Importer(store, w).files([('q.sql', b'select 2;')], {'.sql'})
    view.run()
    assert len(calls) == 2
    store.set_setting(w, 'case_sensitive', True)
    view.run()
    assert len(calls) == 3
    config = json.loads(store.rows('SELECT config FROM llm_profiles')[0]['config'])
    config['max_tokens'] = 9000
    store.execute('UPDATE llm_profiles SET config=?', [json.dumps(config)])
    view.run()
    assert len(calls) == 4
    next(s for s in view.slider if s.label == 'Maximum output share (%)').set_value(40).run()
    assert not view.exception and len(calls) == 5
    st.cache_resource.clear()
