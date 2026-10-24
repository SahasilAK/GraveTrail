import json

import httpx
from test_ai_resumable_files import configured

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.analysis_service import run_analysis
from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


def test_dbt_ai_omission_stays_absent_and_explicit_static_build_uses_static_results(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('dbt extraction choice')
    configured(store, w)
    Importer(store, w).files([('dbt_project.yml', b'name: shop'), ('models/base.sql', b'select 1 as id'),
        ('models/use.sql', b"select id from {{ ref('base') }}"), ('models/ignored.sql', b"select id from {{ ref('base') }}")], set(), source_kind='dbt')
    def provider(request):
        context = json.loads(json.loads(request.content)['messages'][-1]['content'])
        items = []
        for item in context['items']:
            part = item['part']
            result = {'part_id': part['part_id'], 'coverage': 'partial'}
            if item['path'].endswith('use.sql'):
                ref = {k: part[k] for k in ('file_id', 'content_hash', 'start_offset', 'end_offset')}
                result['operations'] = [{'operation_id': 'use', 'kind': 'DBT_MODEL_READ', 'evidence': [ref],
                    'reads': [{'name': 'base'}], 'writes': [{'name': 'use'}]}]
            items.append(result)
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'items': items})}}]})
    result = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider))
    assert result.status == 'committed' and not result.complete
    assert len(store.edges(w)) == 1
    assert store.rows('SELECT count(*) AS n FROM dbt_resources')[0]['n'] == 3
    analyze(store, w, force=True)
    assert len(store.edges(w)) == 2
    store.close()
