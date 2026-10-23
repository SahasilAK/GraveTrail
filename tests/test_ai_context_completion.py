import json

import httpx
import pytest
from test_ai_context_index import prepared
from test_ai_token_budget import model

from dataforge.ai_analysis_models import MissingContext, PartExtraction
from dataforge.ai_context import SourceSnapshot, plan_file_parts
from dataforge.ai_context_index import build_context_index, plan_context_completion


def test_one_completion_only_when_new_relevant_context_is_available():
    consumer = SourceSnapshot('c', 'hc', 'c.sas', '.sas', 'job', '%load;', 'sas')
    definition = SourceSnapshot('d', 'hd', 'd.sas', '.sas', 'job', '%macro load; data b; set a; run; %mend;', 'sas')
    part = plan_file_parts(consumer, {}, model())[0]
    index = build_context_index(prepared(consumer, definition), [])
    item = PartExtraction(part_id=part.part_id, missing_context=[MissingContext(symbol='load', kind='macro', scope='job')])
    works = plan_context_completion([(part, item)], index)
    assert len(works) == 1
    assert works[0].original_part_id == part.part_id
    assert works[0].catalog_revision == index.revision
    assert not plan_context_completion([(part, item)], index, completed={part.part_id})
    item.missing_context[0].consumed_fingerprint = works[0].context.fingerprint
    assert not plan_context_completion([(part, item)], index)
    assert not plan_context_completion([(part, item)], build_context_index(prepared(consumer), []))


@pytest.mark.parametrize('reverse', [False, True])
def test_late_ai_definition_repairs_only_affected_consumer_across_batches(tmp_path, reverse):
    from test_ai_resumable_files import configured

    from dataforge.ai_analysis_models import AnalysisRequest
    from dataforge.analysis_service import run_analysis
    from dataforge.ingestion import Importer
    from dataforge.store import Store
    store = Store(tmp_path)
    workspace = store.create_workspace('late definition')
    configured(store, workspace)
    files = [('consumer.sas', b'%load;'), ('definition.sas', b'opaque registration load reads raw.a writes mart.b;')]
    Importer(store, workspace).files(list(reversed(files)) if reverse else files, {'.sas'})
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
