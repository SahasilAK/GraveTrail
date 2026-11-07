import json

import httpx
import pytest
from test_ai_resumable_files import configured

from dataforge.ai_analysis_models import AnalysisRequest, FileExtraction, OperationRecord, SourceReference
from dataforge.ai_analysis_store import load_file_extractions
from dataforge.ai_linking import link_file_extractions, to_publication_results
from dataforge.analysis_service import analysis_report, run_analysis
from dataforge.configuration import ParsingSettings
from dataforge.ingestion import Importer
from dataforge.services import publish_analysis_results
from dataforge.store import Store
from dataforge.transformations import trace_columns


@pytest.mark.parametrize('cross_file,scope', [(False, ''), (True, ''), (True, 'job')])
def test_resolved_ai_version_chain_traverses_persisted_columns_after_reopen(tmp_path, cross_file, scope):
    store = Store(tmp_path)
    w = store.create_workspace('chain')
    paths = ['a.sql', 'b.sql'] if cross_file else ['a.sql']
    Importer(store, w).files([(p, b'0123456789') for p in paths], {'.sql'})
    inventory = {f['file_id']: {**f, 'source_text': '0123456789'} for f in store.files(w)}
    files = {fid: FileExtraction(file_id=fid, content_hash=m['content_hash'], source_kind='sql', part_ids=['p'],
                               semantic_coverage='model_reported_complete') for fid, m in inventory.items()}
    ids = list(inventory)
    for i in range(3):
        fid = ids[0] if i == 0 or not cross_file else ids[1]
        ref = SourceReference(file_id=fid, content_hash=inventory[fid]['content_hash'], start_offset=0, end_offset=10)
        reads = [] if i == 0 else [{'name': 't', 'version': str(i), 'scope': scope}]
        files[fid].operations.append(OperationRecord.model_validate({
            'operation_id': f'op{i}', 'kind': 'CREATE' if i == 0 else 'UPDATE', 'order': i, 'evidence': [ref],
            'reads': reads, 'writes': [{'name': 't', 'version': str(i+1), 'scope': scope}],
            'derivations': [{'fact_id': f'd{i}', 'target_table': 't', 'target_column': 'amount', 'scope': scope,
                'version': str(i+1), 'evidence': [ref], 'inputs': [] if i == 0 else [
                    {'table': 't', 'column': 'amount', 'scope': scope, 'version': str(i), 'role': 'value'}]}]}))
    config = ParsingSettings().model_dump()
    linked = link_file_extractions(list(files.values()), config)
    publish_analysis_results(store, w, to_publication_results(linked, inventory), config, {})
    targets = store.rows('''SELECT r.column_id,r.asset_id,r.version FROM column_derivations d
        JOIN column_references r ON d.target_column_id=r.column_id ORDER BY r.version''')
    dependencies = store.rows('''SELECT s.column_id,s.version FROM column_dependencies d
        JOIN column_references s ON d.source_column_id=s.column_id ORDER BY s.version''')
    assert [d['column_id'] for d in dependencies] == [t['column_id'] for t in targets[:2]]
    assert len({t['column_id'] for t in targets}) == 3
    root = targets[-1]
    before = trace_columns(store, w, root['asset_id'], root['column_id'])
    assert len(before['derivations']) == 3
    assert len({d['evidence']['operation_id'] for d in before['derivations']}) == 3
    store.close()
    store = Store(tmp_path)
    assert trace_columns(store, w, root['asset_id'], root['column_id']) == before
    store.close()


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


def test_ai_column_ids_keep_case_scopes_and_unresolved_writers_separate(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('separate')
    Importer(store, w).files([('a.sql', b'0123456789')], {'.sql'})
    metadata = store.files(w)[0]
    fid = metadata['file_id']
    ref = SourceReference(file_id=fid, content_hash=metadata['content_hash'], start_offset=0, end_offset=10)
    operations = []
    for i, (table, scope) in enumerate([('Sales', 'left'), ('Sales', 'right'), ('sales', 'left'),
                                       ('conflict', ''), ('conflict', '')]):
        operations.append(OperationRecord.model_validate({'operation_id': f'op{i}', 'kind': 'CREATE', 'order': i,
            'evidence': [ref], 'writes': [{'name': table, 'scope': scope, 'version': '1'}],
            'derivations': [{'fact_id': column, 'target_table': table, 'target_column': column, 'scope': scope,
                'version': '1', 'evidence': [ref]} for column in ('amount', 'Amount')]}))
    file = FileExtraction(file_id=fid, content_hash=metadata['content_hash'], source_kind='sql', part_ids=['p'], operations=operations)
    config = ParsingSettings(case_sensitive=True).model_dump()
    publish_analysis_results(store, w, to_publication_results(link_file_extractions([file], config),
        {fid: {**metadata, 'source_text': '0123456789'}}), config, {})
    rows = store.rows('SELECT target_column_id FROM column_derivations')
    assert len(rows) == len({r['target_column_id'] for r in rows}) == 10
    assert {r['status'] for r in store.rows('''SELECT d.status FROM column_derivations d
        JOIN column_references r ON d.target_column_id=r.column_id JOIN assets a USING(asset_id)
        WHERE a.name='conflict' ''')} == {'unresolved'}
    store.close()
