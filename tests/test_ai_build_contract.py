from contextlib import closing

import pytest

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_context import prepare_analysis
from dataforge.analysis_service import run_analysis
from dataforge.ingestion import Importer
from dataforge.store import Store


def test_mixed_family_selection_is_rejected_before_dispatch(tmp_path):
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('mixed')
        Importer(store, workspace).files([('a.sql', b'select 1;'), ('a.sas', b'data a; run;')], {'.sql', '.sas'})
        with pytest.raises(ValueError, match='one analysis family'):
            prepare_analysis(store, workspace, AnalysisRequest(mode='ai'))


def test_removed_hybrid_start_has_explicit_error(tmp_path):
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('legacy')
        result = run_analysis(store, workspace, AnalysisRequest(mode='hybrid'))
        assert result.status == 'blocked'
        assert 'no longer supported' in result.reasons[0]


def test_explicit_static_build_does_not_restore_project_ai_results(tmp_path, monkeypatch):
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('static')
        Importer(store, workspace).files([('a.sql', b'create table b as select id from a;')], {'.sql'})
        monkeypatch.setattr('dataforge.ai_analysis_store.load_accepted_file_results',
                            lambda *a: (_ for _ in ()).throw(AssertionError('Restored project AI')))
        result = run_analysis(store, workspace, AnalysisRequest(mode='parser'))
        assert result.status == 'committed'
        assert len(store.edges(workspace)) == 1
