from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.analysis_service import preview_analysis
from dataforge.ingestion import Importer
from dataforge.llm import Profile
from ui.common import get_store


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    store = get_store(str(tmp_path))
    w = store.create_workspace('Preparation')
    Importer(store, w).files([('a.sql', b'select 1; select 2;'), ('b.sql', b'select 3;')], {'.sql'})
    profile = Profile(provider='Ollama', base_url='http://localhost:11434', model='m', retries=0)
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', w, 'm', profile.model_dump_json()])
    store.set_setting(w, 'default_profile', 'p')
    yield store, w
    import streamlit as st
    st.cache_resource.clear()


def test_preview_reports_selected_file_and_task_progress_without_provider_calls(workspace, monkeypatch):
    store, w = workspace
    monkeypatch.setattr('dataforge.analysis_service.invoke_analysis_unit', lambda *a, **kw: pytest.fail('Preview sent AI'))
    selected = next(f['file_id'] for f in store.files(w) if f['relative_path'] == 'a.sql')
    events = []
    preview = preview_analysis(store, w, AnalysisRequest(mode='hybrid', file_ids=[selected]),
                               progress=lambda *event: events.append(event))
    assert preview['valid'] and preview['files'] == 1 and preview['units'] == 2
    assert ('Reading selected files', 1, 1) in events
    assert ('Splitting source into tasks', 1, 1) in events
    assert ('Checking prompt budgets and provider credentials', 2, 2) in events
    assert events[-1] == ('Calculating execution budgets', 1, 1)
    assert not store.runs(w)
    assert preview == preview_analysis(store, w, AnalysisRequest(mode='hybrid', file_ids=[selected]))


@pytest.mark.parametrize('blocked', [False, True])
def test_preparation_status_exists_before_calculation_and_keeps_outcome(workspace, monkeypatch, blocked):
    import streamlit as st

    import ui.analysis_ai as ai

    store, w = workspace
    if blocked:
        store.set_setting(w, 'default_profile', '')
    original = ai.preview_analysis
    calls = []
    panels = []
    original_status = st.status

    def status(*args, **kwargs):
        panel = original_status(*args, **kwargs)
        panels.append(panel)
        return panel

    def observed(*args, **kwargs):
        assert panels, 'Preparation must be visible before calculation starts'
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(st, 'status', status)
    monkeypatch.setattr(ai, 'preview_analysis', observed)
    view = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    view.switch_page('ui/pages/analysis.py').run()
    next(c for c in view.checkbox if c.label == 'Use AI for analysis').check().run()
    assert not view.exception
    statuses = view.get('status')
    assert len(statuses) == 1
    assert statuses[0].state == ('error' if blocked else 'complete')
    assert ('Needs attention' if blocked else 'Ready') in statuses[0].label
    assert 'Elapsed:' in statuses[0].label
    assert statuses[0].proto.expanded is blocked
    assert any('Reading selected files' in m.value and '2 / 2' in m.value for m in statuses[0].markdown)
    assert len(calls) == 1
    assert next(b for b in view.button if b.label == 'Analyze with AI + parser').disabled is blocked
    assert not store.runs(w)
    st.cache_resource.clear()


@pytest.mark.parametrize('error', [ValueError('Selected source does not belong to the workspace'),
                                  RuntimeError('Unexpected provider secret must not be displayed')])
def test_preparation_failure_stops_spinner_and_leaves_disabled_action(workspace, monkeypatch, error):
    import ui.analysis_ai as ai

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(ai, 'preview_analysis', fail)
    view = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    view.switch_page('ui/pages/analysis.py').run()
    next(c for c in view.checkbox if c.label == 'Use AI for analysis').check().run()
    assert not view.exception
    status = view.get('status')[0]
    assert status.state == 'error' and status.proto.expanded
    assert 'Preparation failed' in status.label
    if isinstance(error, ValueError):
        assert any(str(error) in warning.value for warning in status.warning)
    else:
        assert status.error
    assert next(b for b in view.button if b.label == 'Analyze with AI + parser').disabled
    assert not any('Unexpected provider secret' in text.value for text in view.markdown)
