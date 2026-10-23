import json

import httpx
import pytest
from test_ai_resumable_files import configured

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_analysis_store import load_file_extractions
from dataforge.ai_linking import link_file_extractions, to_publication_results
from dataforge.analysis_service import run_analysis
from dataforge.ingestion import Importer
from dataforge.store import Store


@pytest.mark.parametrize('family', ['sql', 'sas', 'dbt'])
def test_independent_three_file_chain_publishes_and_relinks_without_provider(tmp_path, monkeypatch, family):
    store = Store(tmp_path)
    workspace = store.create_workspace(family)
    configured(store, workspace)
    fixtures = {}
    for i in range(3):
        source, target = ('raw.input' if i == 0 else f't{i-1}'), f't{i}'
        code = (f'data {target}; set {source}; id=id; run;' if family == 'sas' else
                f'create table {target} as select id from {source};')
        if family == 'dbt':
            code = 'select id from ' + ("{{ source('raw', 'input') }}" if i == 0 else "{{ ref('t" + str(i-1) + "') }}")
        path = ('models/' if family == 'dbt' else '') + target + ('.sas' if family == 'sas' else '.sql')
        fixtures[path] = (source, target, code)
    files = [(path, code.encode()) for path, (_, _, code) in fixtures.items()]
    if family == 'dbt':
        files += [('dbt_project.yml', b'name: shop\nversion: 1.0'),
                  ('models/schema.yml', b'version: 2\nsources:\n  - name: raw\n    tables:\n      - name: input')]
    Importer(store, workspace).files(files, {'.sql', '.sas'} if family != 'dbt' else set(), source_kind='dbt' if family == 'dbt' else 'files')
    def provider(request):
        context = json.loads(json.loads(request.content)['messages'][-1]['content'])
        items = []
        for item in context['items']:
            part, path = item['part'], item['path']
            result = {'part_id': part['part_id'], 'coverage': 'complete'}
            if path in fixtures:
                source, target, code = fixtures[path]
                ref = {k: part[k] for k in ('file_id', 'content_hash', 'start_offset', 'end_offset')}
                expr = {**ref, 'start_offset': code.index('id'), 'end_offset': code.index('id') + 2}
                result['operations'] = [{'operation_id': target, 'kind': 'CREATE', 'evidence': [ref],
                    'reads': [{'name': source}], 'writes': [{'name': target}],
                    'derivations': [{'fact_id': target + ':id', 'target_table': target, 'target_column': 'id',
                        'inputs': [{'table': source, 'column': 'id', 'role': 'value'},
                                   {'table': source, 'column': 'id', 'role': 'row_filter'}],
                        'evidence': [ref], 'expression': expr}]}]
            items.append(result)
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'items': items})}, 'finish_reason': 'stop'}]})
    monkeypatch.setattr('dataforge.services.prepare_analysis_results', lambda *a, **k: pytest.fail('Static parser preparation called'))
    result = run_analysis(store, workspace, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider))
    assert result.status == 'committed', result.reasons
    assert len(store.edges(workspace)) == 3
    actual = {(r['source'], r['target']) for r in store.rows('''SELECT a.name AS source,b.name AS target
        FROM edges e JOIN assets a ON e.source_id=a.asset_id JOIN assets b ON e.target_id=b.asset_id
        WHERE e.workspace_id=?''', [workspace])}
    assert actual == {('raw.input', 't0'), ('t0', 't1'), ('t1', 't2')}
    assert store.rows('SELECT count(*) AS n FROM column_derivations')[0]['n'] == 3
    assert store.rows('SELECT count(*) AS n FROM column_dependencies')[0]['n'] == 6
    if family == 'dbt':
        assert store.rows('SELECT count(*) AS n FROM dbt_resources')[0]['n'] >= 4
    saved = load_file_extractions(store, workspace, result.run_id)
    inventory = {f['file_id']: {**f, 'source_text': store.snapshot_content(f)} for f in store.files(workspace)}
    before = [p.to_dict() for _, p in to_publication_results(link_file_extractions(saved, {}), inventory)]
    store.close()
    store = Store(tmp_path)
    after = [p.to_dict() for _, p in to_publication_results(link_file_extractions(load_file_extractions(store, workspace, result.run_id), {}), inventory)]
    assert before == after
    store.close()
