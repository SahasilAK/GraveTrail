from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_context import PreparedAnalysis, SourceSnapshot, plan_ai_units


def test_screenshot_shape_has_2200_files_and_6238_complete_units():
    sources = tuple(SourceSnapshot(str(i), str(i), f'{i}.sql', '.sql', 'workspace',
        'select 1; select 2; select 3;' if i < 1838 else 'select 1; select 2;') for i in range(2200))
    prepared = PreparedAnalysis('qualification', AnalysisRequest(mode='ai'), sources, '{}')
    plan = plan_ai_units(prepared)
    assert len(plan.units) == 6238 and len(plan.disclosure) == 2200
    assert not plan.blocked
    assert len({u.unit_id for u in plan.units}) == 6238
