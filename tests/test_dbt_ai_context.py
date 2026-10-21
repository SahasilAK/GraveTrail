import json

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_context import plan_ai_units, prepare_analysis
from dataforge.ingestion import Importer
from dataforge.store import Store


def test_dbt_models_keep_project_context_and_macros_are_context_only(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('dbt ai')
    Importer(store, w).files([
        ('dbt_project.yml', b'name: shop'),
        ('models/base.sql', b'select 1 as id'),
        ('models/use.sql', b"select {{ twice('id') }} as id from {{ ref('base') }}"),
        ('macros/twice.sql', b'{% macro twice(x) %}{{ x }} * 2{% endmacro %}'),
        ('macros/unrelated.sql', b'{% macro unrelated() %}1{% endmacro %}'),
    ], set(), source_kind='dbt')
    prepared = prepare_analysis(store, w, AnalysisRequest(mode='ai'))
    plan = plan_ai_units(prepared)
    assert len(plan.units) == 2
    unit = next(u for u in plan.units if u.path.endswith('use.sql'))
    context = json.dumps(plan.context_for(unit))
    assert 'twice' in context and 'base' in context and 'shop' in context
    assert 'unrelated.sql' not in context
    assert 'relationships' not in context and 'derivations' not in context
    assert unit.source_kind == 'dbt'
    assert any(d.get('disposition') == 'context_only' for d in plan.disclosure)
    store.close()
