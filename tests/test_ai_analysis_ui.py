from pathlib import Path

from streamlit.testing.v1 import AppTest

from dataforge.ingestion import Importer
from ui.common import get_store


def test_preparation_database_lock_does_not_block_cancel_render(tmp_path, monkeypatch):
    import threading

    import streamlit as st

    import ui.analysis_ai as ai
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    store = get_store(str(tmp_path))
    workspace = store.create_workspace('small')
    entered, release = threading.Event(), threading.Event()
    class PendingJobs:
        def read(self, *args):
            return {'status': 'running', 'progress': 0, 'stage': 'Preparing', 'run_id': 'r'}
    monkeypatch.setattr(ai, 'analysis_jobs', lambda *a: PendingJobs())
    def app(store, workspace):
        import streamlit as st

        from ui.analysis_ai import progress
        st.session_state['ai_analysis_job_' + workspace] = 'job'
        progress(store, workspace)
    def locked_preparation():
        with store.lock:
            entered.set()
            release.wait(6)
    worker = threading.Thread(target=locked_preparation)
    worker.start()
    try:
        assert entered.wait(2)
        view = AppTest.from_function(app, args=(store, workspace), default_timeout=2).run()
        assert not view.exception
        assert any(b.label == 'Cancel AI analysis' and not b.disabled for b in view.button)
        assert any('checkpoint' in c.value.lower() for c in view.caption)
    finally:
        release.set()
        worker.join()
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
    record.update(status='cancelled', progress=1, result={'status': 'cancelled'})
    view.run()
    assert not view.exception and len(previews) == 1
    assert not any(p.proto.value == 100 for p in view.get('progress')), 'Cancelled work is not 100% complete'
    assert next(c for c in view.checkbox if c.label == 'Use AI for analysis').value
    st.cache_resource.clear()
