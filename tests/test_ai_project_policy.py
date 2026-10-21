import pytest
from pydantic import ValidationError

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_budget import execution_budget


def test_new_policy_is_bounded_and_legacy_json_loads():
    request = AnalysisRequest.model_validate({'mode': 'ai'})
    assert request.auto_continue is True
    assert request.max_files_per_request is None
    for field, values in [('max_files_per_request', [0, 101]), ('max_parallel_requests', [0, 5])]:
        for value in values:
            with pytest.raises(ValidationError):
                AnalysisRequest(**{field: value})
    assert AnalysisRequest(max_files_per_request=100, max_parallel_requests=4)


def test_project_ceiling_is_distinct_from_execution_window():
    from dataforge.ai_budget import resolve_project_allowance
    bundles = [(2, 4096, 120)] * 6238
    allowance = resolve_project_allowance(bundles, AnalysisRequest(mode='ai'))
    assert allowance['extraction_attempts'] == 12476
    assert allowance['max_provider_attempts'] >= 12476
    assert allowance['max_output_tokens_total'] > 2000000
    assert execution_budget(bundles)['effective']['max_provider_attempts'] == 2000
    assert all(type(v) is int and v > 0 for k, v in allowance.items() if k.startswith('max_'))


def test_custom_project_caps_cannot_be_silently_enlarged():
    from dataforge.ai_budget import resolve_project_allowance
    allowance = resolve_project_allowance([(2, 4096, 120)] * 3,
        AnalysisRequest(project_max_provider_attempts=1))
    assert allowance['max_provider_attempts'] == 1
