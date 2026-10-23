import json

import httpx
import pytest
from test_ai_resumable_files import configured, empty_provider

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.analysis_service import run_analysis
from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


@pytest.mark.parametrize('failure', ['source_change', 'cancel', 'invalid_evidence', 'permission_change'])
def test_failed_or_stale_build_preserves_previous_graph(tmp_path, failure):
    store = Store(tmp_path)
    w = store.create_workspace('atomic publication')
    configured(store, w)
    Importer(store, w).files([('q.sql', b'create table b as select id from a;')], {'.sql'})
    analyze(store, w)
    previous = store.edges(w)
    cancelled = [False]
    seen = []
    normal = empty_provider(seen)
    def provider(request):
        if failure == 'source_change':
            store.execute("UPDATE source_files SET content_hash='changed' WHERE workspace_id=?", [w])
        elif failure == 'cancel':
            cancelled[0] = True
        elif failure == 'permission_change':
            store.set_setting(w, 'external_llm', True)
        elif failure == 'invalid_evidence':
            context = json.loads(json.loads(request.content)['messages'][-1]['content'])
            part = context['items'][0]['part']
            body = {'items': [{'part_id': part['part_id'], 'operations': [{'operation_id': 'x', 'kind': 'READ',
                'evidence': [{'file_id': 'forged', 'content_hash': 'forged', 'start_offset': 0, 'end_offset': 1}]}]}]}
            return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(body)}}]})
        return normal(request)
    result = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider), cancelled=lambda: cancelled[0])
    assert result.status in {'stale', 'cancelled', 'failed'}
    assert store.edges(w) == previous
    assert not store.rows("SELECT * FROM ai_analysis_runs WHERE status='committed'")
    store.close()


def test_parser_build_needs_no_provider_and_no_project_ai_restore(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('offline static')
    Importer(store, w).files([('q.sql', b'create table b as select id from a;')], {'.sql'})
    result = run_analysis(store, w, AnalysisRequest(mode='parser'))
    assert result.status == 'committed' and len(store.edges(w)) == 1
    store.close()


def test_new_runs_do_not_silently_reuse_earlier_ai_extraction(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('new extraction')
    configured(store, w)
    Importer(store, w).files([('q.sql', b'select 1;')], {'.sql'})
    seen = []
    for _ in range(2):
        result = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(empty_provider(seen)))
        assert result.status == 'committed'
        assert not result.complete  # A model's completeness assertion is not proof.
    assert len(seen) == 2
    store.close()
