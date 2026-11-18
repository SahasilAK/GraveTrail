from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from dataforge.ingestion import Importer
from ui.common import get_store


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    store = get_store(str(tmp_path))
    w = store.create_workspace('Preparation')
    Importer(store, w).files([('a.sql', b'select 1; select 2;'), ('b.sql', b'select 3;')], {'.sql'})
    from test_ai_resumable_files import configured
    configured(store, w)
    yield store, w
    import streamlit as st
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
    assert next(b for b in view.button if b.label == 'Analyze with AI').disabled
    assert not any('Unexpected provider secret' in text.value for text in view.markdown)
