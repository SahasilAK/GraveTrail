from dataforge.ai_analysis_models import (
    AnalysisRequest,
    EvidenceCitation,
    ProjectLineageResponse,
    TableRelationship,
    UnitAttemptResult,
)
from dataforge.analysis_service import run_analysis
from dataforge.ingestion import Importer
from dataforge.llm import Profile
from dataforge.store import Store


def test_dbt_ai_publishes_only_validated_ai_table_facts(tmp_path, monkeypatch):
    store = Store(tmp_path)
    w = store.create_workspace('dbt ai publication')
    Importer(store, w).files([
        ('dbt_project.yml', b'name: shop'), ('models/base.sql', b'select 1 as id'),
        ('models/use.sql', b"select id from {{ ref('base') }}"),
        ('models/ignored.sql', b"select id from {{ ref('base') }}"),
    ], set(), source_kind='dbt')
    p = Profile(provider='Ollama', base_url='http://localhost:11434', model='m', retries=0, context_chars=100000)
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', w, 'm', p.model_dump_json()])
    store.set_setting(w, 'default_profile', 'p')
    store.set_setting(w, 'max_context_chars', 100000)
    def extract(s, w, u, t, e):
        response = ProjectLineageResponse(unit_id=u.unit_id)
        if u.path.endswith('use.sql'):
            response.relationships.append(TableRelationship(source='base', target='use', operation='DBT_MODEL_READ',
                evidence=EvidenceCitation.from_unit(u)))
        return UnitAttemptResult(unit_id=u.unit_id, task=t, result=response)
    monkeypatch.setattr('dataforge.analysis_service.invoke_analysis_unit', extract)
    report = run_analysis(store, w, AnalysisRequest(mode='ai', max_files_per_request=1, max_parallel_requests=1))
    assert report.status == 'committed', report.reasons
    edges = store.edges(w)
    assert len(edges) == 1
    assert edges[0]['method'] == 'ai-project'
    assert store.rows('SELECT count(*) AS n FROM dbt_resources')[0]['n'] == 3
    # Reopening/parser refresh must not restore withheld static edges.
    from dataforge.services import analyze
    analyze(store, w)
    assert len(store.edges(w)) == 1
    store.close()
