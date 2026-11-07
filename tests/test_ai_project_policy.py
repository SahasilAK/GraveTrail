import pytest

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.analysis_service import run_analysis
from dataforge.store import Store


@pytest.mark.parametrize('removed', [{'mode': 'hybrid'}, {'additional_ai_review': True},
    {'max_context_chars': 8000}, {'max_parallel_requests': 2}, {'auto_continue': False},
    {'project_max_provider_attempts': 10}, {'max_files_per_request': 8}])
def test_removed_start_contracts_return_explicit_compatibility_errors(tmp_path, removed):
    store = Store(tmp_path)
    w = store.create_workspace('policy')
    result = run_analysis(store, w, AnalysisRequest(**{'mode': 'ai', **removed}))
    assert result.status == 'blocked'
    assert 'no longer supported' in result.reasons[0]
    assert not store.rows('SELECT * FROM ai_analysis_attempts')
    store.close()
