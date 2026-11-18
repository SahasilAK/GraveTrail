import json

import httpx


def test_late_ai_definition_repairs_only_affected_consumer_across_batches(tmp_path):
    from test_ai_resumable_files import configured

    from dataforge.ai_analysis_models import AnalysisRequest
    from dataforge.analysis_service import run_analysis
    from dataforge.ingestion import Importer
    from dataforge.store import Store
    store = Store(tmp_path)
    workspace = store.create_workspace('late definition')
    configured(store, workspace)
    Importer(store, workspace).files([('definition.sas', b'opaque registration load reads raw.a writes mart.b;'),
                                    ('consumer.sas', b'%load;')], {'.sas'})
    seen, first = [], [True]
    def provider(request):
        context = json.loads(json.loads(request.content)['messages'][-1]['content'])
        items = []
        for item in context['items']:
            part = item['part']
            seen.append((item['path'], part['work_kind']))
            ref = {k: part[k] for k in ('file_id', 'content_hash', 'start_offset', 'end_offset')}
            result = {'part_id': part['part_id'], 'coverage': 'complete'}
            if item['path'] == 'definition.sas':
                if first[0]:
                    continue  # Valid sibling consumer is saved before this missing item is retried.
                result['definitions'] = [{'entry_id': 'load-definition', 'symbol': 'load', 'kind': 'macro',
                    'source_kind': 'sas', 'scope': 'workspace', 'origin': 'ai_inferred', 'evidence': [ref]}]
            elif part['work_kind'] == 'extraction':
                result['missing_context'] = [{'symbol': 'load', 'kind': 'macro', 'scope': 'workspace', 'evidence': [ref]}]
            else:
                assert context['definitions'][0]['symbol'] == 'load'
                result['operations'] = [{'operation_id': 'load', 'kind': 'MACRO_CALL', 'evidence': [ref],
                    'reads': [{'name': 'raw.a'}], 'writes': [{'name': 'mart.b'}]}]
            items.append(result)
        first[0] = False
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'items': items})}, 'finish_reason': 'stop'}]})
    result = run_analysis(store, workspace, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider))
    assert result.status == 'committed', result.reasons
    assert len(store.edges(workspace)) == 1
    assert seen.count(('consumer.sas', 'extraction')) == 1
    assert seen.count(('consumer.sas', 'context_completion')) == 1
    assert ('definition.sas', 'context_completion') not in seen
    store.close()
