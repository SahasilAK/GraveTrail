from test_ai_file_parts import source
from test_ai_linking_review import op
from test_ai_token_budget import model

from dataforge.ai_analysis_models import (
    PartExtraction,
    ResourceReference,
    SourceReference,
)
from dataforge.ai_batching import pack_request
from dataforge.ai_composition import plan_file_consolidation
from dataforge.ai_context import plan_file_parts


def consolidation_fixture():
    snapshot = source('x' * 16000)
    profile = model(70000).model_copy(update={'max_tokens': 4000})
    parts = plan_file_parts(snapshot, {}, profile)
    records = []
    for i, part in enumerate(parts):
        operations = []
        for j in range(12):
            operation = op(f'operation{j}', writes=[f't{j}'])
            operation.evidence = [SourceReference(file_id=part.file_id, content_hash=part.content_hash,
                start_offset=part.start_offset, end_offset=part.end_offset)]
            operations.append(operation)
        records.append((part, PartExtraction(part_id=part.part_id, operations=operations)))
    context = {'sources': {snapshot.file_id: snapshot}, 'settings': {'case_sensitive': True}}
    return records, profile, context

def test_shared_scope_is_partitioned_and_each_group_fits_dispatch():
    records, profile, context = consolidation_fixture()
    work = plan_file_consolidation(records, profile)
    assert len(work) > 1 and not any(w.overflow for w in work)
    assert {op['operation_id'] for w in work for op in w.inputs['operations']} == {f'operation{j}' for j in range(12)}
    for w in work:
        assert pack_request([w.part], profile, {**context, 'work_inputs': {w.part.part_id: w.inputs}}).budget.fits
    reversed_work = plan_file_consolidation(list(reversed(records)), profile)
    assert [w.part.part_id for w in work] == [w.part.part_id for w in reversed_work]

def test_consolidation_planning_uses_actual_dispatch_settings():
    records, profile, context = consolidation_fixture()
    context['settings']['large'] = 'x' * 100000
    work = plan_file_consolidation(records, profile, context=context)
    assert work and all(w.overflow for w in work)

def test_connected_oversized_component_is_not_split_or_truncated():
    records, profile, context = consolidation_fixture()
    for _, result in records:
        for j, operation in enumerate(result.operations):
            if j:
                operation.reads = [ResourceReference(name=f't{j-1}')]
    work = plan_file_consolidation(records, profile, context=context)
    assert len(work) == 1 and work[0].overflow
    assert len(work[0].inputs['operations']) == sum(len(r.operations) for _, r in records)
    assert set(work[0].inputs['part_ids']) == {p.part_id for p, _ in records}

def test_completed_consolidation_groups_reused_after_reopen(tmp_path, monkeypatch):
    import json

    import httpx
    from test_ai_resumable_files import configured

    from dataforge.ai_analysis_models import AnalysisRequest
    from dataforge.ai_analysis_store import load_file_extractions, save_part_extraction
    from dataforge.analysis_service import run_analysis
    from dataforge.ingestion import Importer
    from dataforge.store import Store

    store = Store(tmp_path)
    workspace = store.create_workspace('group resume')
    configured(store, workspace, model().model_copy(update={'max_tokens': 4000}))
    Importer(store, workspace).files([('large.sql', b'x' * 16000)], {'.sql'})
    calls, stopped = [], [False]

    def provider(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        items = []
        for item in ctx['items']:
            part = item['part']
            calls.append((part['work_kind'], part['part_id']))
            operations = []
            if part['work_kind'] == 'extraction':
                ref = {k: part[k] for k in ('file_id', 'content_hash', 'start_offset', 'end_offset')}
                operations = [dict(operation_id=f'op{j}', kind='CREATE', order=j, evidence=[ref],
                                   writes=[{'name': f't{j}'}]) for j in range(12)]
            items.append({'part_id': part['part_id'], 'operations': operations, 'coverage': 'complete'})
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'items': items})}}]})

    def checkpoint(*args, **kwargs):
        save_part_extraction(*args, **kwargs)
        if args[3].work_kind == 'consolidation':
            stopped[0] = True

    monkeypatch.setattr('dataforge.analysis_service.save_part_extraction', checkpoint)
    first = run_analysis(store, workspace, AnalysisRequest(mode='ai'), cancelled=lambda: stopped[0],
                         transport=httpx.MockTransport(provider))
    assert first.status == 'cancelled', first.reasons
    store.close()
    monkeypatch.setattr('dataforge.analysis_service.save_part_extraction', save_part_extraction)
    store = Store(tmp_path)
    resumed = run_analysis(store, workspace, AnalysisRequest(mode='ai', resume_run_id=first.run_id),
                           transport=httpx.MockTransport(provider))
    assert resumed.status == 'committed', resumed.reasons
    assert len(calls) == len(set(calls))
    assert sum(kind == 'consolidation' for kind, _ in calls) > 1
    final = load_file_extractions(store, workspace, first.run_id)[0]
    assert len(final.operations) == 12 * len(final.part_ids)
    assert not final.unresolved
    store.close()
