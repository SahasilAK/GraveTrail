import json

import httpx
import pytest
from test_ai_resumable_files import configured

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_analysis_store import load_file_extractions
from dataforge.ai_linking import link_file_extractions
from dataforge.analysis_service import analysis_report, run_analysis
from dataforge.ingestion import Importer
from dataforge.store import Store


@pytest.mark.parametrize('mode', ['publication_only', 'both', 'clean_selected'])
def test_publication_uncertainty_counts_survive_selected_run_and_reopen(tmp_path, mode):
    store = Store(tmp_path)
    w = store.create_workspace('counts')
    configured(store, w)
    Importer(store, w).files([('a.sql', b'select 1;'), ('b.sql', b'select 2;')], {'.sql'})
    phase = [0]

    def provider(request):
        items = []
        context = json.loads(json.loads(request.content)['messages'][-1]['content'])
        for item in context['items']:
            part = item['part']
            ref = {k: part[k] for k in ('file_id', 'content_hash', 'start_offset', 'end_offset')}
            ambiguous = item['path'] == 'b.sql' or mode != 'clean_selected' or phase[0] == 0
            result = {'part_id': part['part_id'], 'coverage': 'complete', 'operations': [{
                'operation_id': 'read', 'kind': 'CREATE', 'evidence': [ref],
                'reads': [{'name': 't', 'scope': s} for s in ('left', 'right')], 'writes': [{'name': item['path']}],
                'usages': [{'table': 't', 'column': col, 'context': 'value', 'evidence': [ref],
                            'scope': '' if ambiguous else 'left'} for col in ('x', 'y')]}]}
            if phase[0] and mode == 'both':
                result.update(coverage='partial', unresolved=['extracted_gap'])
            items.append(result)
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'items': items})}}]})

    first = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider))
    assert first.status == 'committed', first.reasons
    selected = next(f['file_id'] for f in store.files(w) if f['relative_path'] == 'a.sql')
    phase[0] = 1
    result = run_analysis(store, w, AnalysisRequest(mode='ai', file_ids=[selected]), transport=httpx.MockTransport(provider))
    assert result.status == 'committed', result.reasons
    saved = load_file_extractions(store, w, result.run_id)
    assert len(saved) == 1 and not link_file_extractions(saved, {}).unresolved
    assert result.counts['analyzed'] == 1
    assert result.counts['incomplete_files'] == (0 if mode == 'clean_selected' else 1)
    assert result.counts['coverage_gaps'] == (0 if mode == 'clean_selected' else 2)
    assert result.counts['unresolved'] == {'publication_only': 1, 'both': 2, 'clean_selected': 0}[mode]
    report = analysis_report(store, w, result.run_id)
    assert report['summary']['counts'] == result.counts
    assert not result.complete
    store.close()
    store = Store(tmp_path)
    assert analysis_report(store, w, result.run_id)['summary']['counts'] == result.counts
    store.close()
