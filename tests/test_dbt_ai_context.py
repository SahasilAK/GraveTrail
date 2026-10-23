import json

from test_ai_token_budget import model

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_context import plan_file_parts, prepare_analysis
from dataforge.ai_context_index import build_context_index, context_for_part
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
    parts = [p for source in prepared.sources for p in plan_file_parts(source, {}, model())]
    assert len(parts) == 5  # Context-only sources are also processed completely.
    unit = next(p for p in parts if p.file_id == next(s.file_id for s in prepared.sources if s.path.endswith('use.sql')))
    index = build_context_index(prepared, [])
    selection = context_for_part(index, unit, 20000)
    context = json.dumps(selection.wire)
    assert 'twice' in context and 'base' in context and 'shop' in context
    assert 'unrelated.sql' not in context
    assert 'relationships' not in context and 'derivations' not in context
    assert unit.source_kind == 'dbt'
    store.close()
