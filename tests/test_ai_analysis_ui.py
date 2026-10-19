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
            return {'status': 'completed', 'progress': 1., 'stage': 'Publication complete',
                    'result': {'status': 'committed', 'run_id': 'finished'}}

    monkeypatch.setattr('ui.analysis_ai.analysis_jobs', lambda *args: CompletedJobs())
    view = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    view.session_state['ai_analysis_job_' + w] = 'job'
    view.session_state['ai_report_choice_' + w] = 'older'
    view.switch_page('ui/pages/analysis.py').run()
    assert not view.exception
    assert view.session_state['ai_analysis_refreshed_' + w] == 'job'
    assert view.session_state['ai_report_choice_' + w] == 'finished'
    assert any('Requests: 1' in text.value and 'accepted: 3' in text.value for text in view.markdown)
    import streamlit as st
    st.cache_resource.clear()
