import json

import httpx

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.analysis_service import run_analysis
from dataforge.database_maintenance import inspect_database
from dataforge.ingestion import Importer
from dataforge.llm import Profile
from dataforge.store import Store


def configured(store, w):
    p = Profile(provider='OpenAI compatible', base_url='http://localhost:1234', model='m',
                retries=0, context_chars=100000, max_tokens=8192)
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', w, 'm', p.model_dump_json()])
    for k, v in [('default_profile', 'p'), ('max_context_chars', 100000), ('llm_concurrency', 2)]:
        store.set_setting(w, k, v)


def test_single_start_builds_mixed_sources_with_real_batch_transport(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('mixed pipeline')
    configured(store, w)
    Importer(store, w).files([('q.sql', b'create table mart.out as select id from raw.a;'),
                              ('q.sas', b'data work.out; set raw.sas; run;')], {'.sql', '.sas'})
    Importer(store, w).files([('dbt_project.yml', b'name: shop'),
        ('models/base.sql', b'select 1 as id'),
        ('models/use.sql', b"select id from {{ ref('base') }}")], set(), source_kind='dbt')
    seen = []
    def provider(request):
        body = json.loads(request.content)
        text = body['messages'][1]['content']
        ctx = json.loads(text[text.find('{'):])
        contexts = ctx.get('items', [ctx])
        results = []
        for context in contexts:
            u = context['unit']
            seen.append(u['unit_id'])
            result = {'unit_id': u['unit_id'], 'coverage': {'status': 'partial'}}
            target = 'mart.out' if u['path'] == 'q.sql' else 'use' if u['path'].endswith('/use.sql') else None
            if target:
                source = 'raw.a' if target == 'mart.out' else 'base'
                operation = 'CREATE' if target == 'mart.out' else 'DBT_MODEL_READ'
                result.update(relationships=[{'source': source, 'target': target, 'operation': operation,
                    'evidence': {'unit_id': u['unit_id']}}], derivations=[{
                    'target_table': target, 'target_column': 'id', 'expression': 'id', 'category': 'direct',
                    'inputs': [{'table': source, 'column': 'id'}], 'evidence': {'unit_id': u['unit_id']}}])
            results.append(result)
        payload = {'items': results} if 'items' in ctx else results[0]
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(payload)}, 'finish_reason': 'stop'}],
                                       'usage': {'prompt_tokens': 10, 'completion_tokens': 10}})
    result = run_analysis(store, w, AnalysisRequest(mode='ai', max_files_per_request=2, max_parallel_requests=2),
                          transport=httpx.MockTransport(provider))
    assert result.status == 'committed', result.reasons
    assert len(seen) == len(set(seen)) == 4
    assert len(store.edges(w)) == 2
    assert store.rows('SELECT count(*) AS n FROM column_derivations')[0]['n'] == 2
    assert inspect_database(store)['ok']
    assert store.rows('SELECT count(*) AS n FROM ai_link_checkpoints')[0]['n'] == 1
    store.close()


def test_parallel_unknown_response_needs_explicit_retry_after_reopen(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('unknown parallel')
    configured(store, w)
    Importer(store, w).files([('a.sql', b'select 1;'), ('b.sql', b'select 2;')], {'.sql'})
    calls = []
    def lost(request):
        calls.append(1)
        raise httpx.ReadTimeout('synthetic loss')
    result = run_analysis(store, w, AnalysisRequest(mode='ai', max_parallel_requests=2),
                          transport=httpx.MockTransport(lost))
    assert result.status == 'awaiting_continuation'
    store.close()
    store = Store(tmp_path)
    resumed = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=result.run_id),
                           transport=httpx.MockTransport(lost))
    assert resumed.reasons == ['unknown_inflight_request_requires_explicit_retry']
    assert len(calls) == 2
    store.close()
