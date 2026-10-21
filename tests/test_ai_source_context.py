from dataclasses import replace

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_context import AIExecutionContext, PreparedAnalysis, SourceSnapshot, plan_ai_units
from dataforge.analysis_service import _unit_context_hash


def test_unrelated_source_does_not_invalidate_unit_but_new_schema_does():
    source = SourceSnapshot('f', 'h', 'a.sql', '.sql', 'w', 'select * from a;')
    prepared = PreparedAnalysis('w', AnalysisRequest(mode='ai'), (source,), '{}')
    execution = AIExecutionContext(prepared.request)
    plan = plan_ai_units(prepared)
    unit = plan.units[0]
    first = _unit_context_hash(prepared, plan, execution, unit, 'old')
    other = SourceSnapshot('o', 'new', 'o.sql', '.sql', 'w', 'select x from unrelated;')
    updated = replace(prepared, sources=(source, other), manifest_hash='changed')
    assert _unit_context_hash(updated, plan_ai_units(updated), execution, unit, 'new') == first
    definition = replace(other, code='create table a (id int);')
    updated = replace(updated, sources=(source, definition))
    assert _unit_context_hash(updated, plan_ai_units(updated), execution, unit, 'new') != first
