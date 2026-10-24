"""Recovery uses mock responses, never provider/model accuracy as an oracle."""
import json
from collections import Counter
from dataclasses import replace

import httpx
import pytest
from test_ai_file_parts import source
from test_ai_resumable_files import configured
from test_ai_token_budget import model

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_analysis_store import load_file_parts
from dataforge.ai_batching import pack_request
from dataforge.ai_context import plan_file_parts
from dataforge.analysis_service import analysis_report, run_analysis
from dataforge.ingestion import Importer
from dataforge.store import Store


def envelope(items, finish='stop'):
    content = items if isinstance(items, str) else json.dumps({'items': items})
    return httpx.Response(200, json={'choices': [{'message': {'content': content}, 'finish_reason': finish}],
        'usage': {'prompt_tokens': 11, 'completion_tokens': 23}})


def setup_run(tmp_path, files=1, profile=None):
    store = Store(tmp_path)
    w = store.create_workspace('recovery')
    configured(store, w, profile)
    Importer(store, w).files([(f'{i}.sql', b'select 1;' + b' ' * 1000) for i in range(files)], {'.sql'})
    return store, w


@pytest.mark.parametrize('fault,code', [('missing', 'missing_extraction_item'), ('unknown', 'missing_extraction_item'),
    ('duplicate', 'duplicate_response_part'), ('schema', 'invalid_extraction_item'),
    ('citation', 'invalid_source_reference'), ('json', 'invalid_extraction_json'),
    ('envelope', 'invalid_extraction_envelope')])
def test_invalid_items_recover_with_safe_feedback_and_keep_siblings(tmp_path, monkeypatch, fault, code):
    import dataforge.analysis_service as service
    monkeypatch.setattr(service, 'recovery_wait', lambda seconds, check: check(), raising=False)
    # Advance durable due times without actually sleeping in a mock qualification.
    clock = [1000.]
    monkeypatch.setattr(service, 'time', lambda: clock[0], raising=False)
    def wait(seconds, check):
        clock[0] += seconds
        check()
    monkeypatch.setattr(service, 'recovery_wait', wait, raising=False)
    store, w = setup_run(tmp_path, files=12)
    calls, seen, failures = [], Counter(), Counter()
    difficult = set()
    def provider(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        calls.append(ctx)
        if not difficult:
            difficult.update(i['part']['part_id'] for i in ctx['items'][:2])
        items = []
        for i in ctx['items']:
            pid = i['part']['part_id']
            seen[pid] += 1
            good = {'part_id': pid, 'coverage': 'no_operations'}
            if pid in difficult and failures[pid] < 2:
                failures[pid] += 1
                if fault == 'missing':
                    continue
                if fault == 'duplicate':
                    items.extend([good, good])
                    continue
                if fault == 'schema':
                    good['operations'] = 'DO_NOT_PERSIST source Authorization: secret'
                if fault == 'unknown':
                    good['part_id'] = 'DO_NOT_PERSIST'
                if fault == 'citation':
                    ref = {k: i['part'][k] for k in ('file_id', 'content_hash', 'start_offset', 'end_offset')}
                    ref['content_hash'] = 'DO_NOT_PERSIST'
                    good.update(coverage='complete', operations=[{'operation_id': 'bad', 'kind': 'READ', 'evidence': [ref]}])
                if fault in {'json', 'envelope'}:
                    return envelope('{"private":"DO_NOT_PERSIST"' if fault == 'json' else '{"private":"DO_NOT_PERSIST"}')
            items.append(good)
        return envelope(items)
    result = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider))
    assert result.status == 'committed', result.reasons
    saved = load_file_parts(store, w, result.run_id)
    assert len(saved) == 12
    if fault not in {'json', 'envelope'}:
        assert all(n == (3 if pid in difficult else 1) for pid, n in seen.items())
        assert len(calls[1]['items']) < len(calls[0]['items'])
    feedback = [i['validation_feedback'] for ctx in calls for i in ctx['items'] if 'validation_feedback' in i]
    assert any(f['code'] == code for f in feedback)
    if fault == 'schema':
        assert any('operations' in f['path'] for f in feedback)
    report = analysis_report(store, w, result.run_id)
    diagnostics = [d for r in store.rows('SELECT details FROM ai_analysis_requests')
                   for d in json.loads(r['details']).get('diagnostics', [])]
    assert diagnostics and all(d['stage'] == 'extracting' and d['request_id'] and d['attempt_number'] for d in diagnostics)
    if fault == 'unknown':
        assert any(d['code'] == 'unknown_response_part' and d['part_id'] is None for d in diagnostics)
    assert 'DO_NOT_PERSIST' not in json.dumps([report['summary'], diagnostics, feedback])
    assert len(store.rows('SELECT * FROM analysis_runs')) == 1
    store.close()


def test_persistent_failure_waits_cancellably_and_resumes_queue_without_repeating_good_parts(tmp_path, monkeypatch):
    import dataforge.analysis_service as service
    stopped, waits = [False], []
    def wait(seconds, check):
        waits.append(seconds)
        stopped[0] = True
        check()
    monkeypatch.setattr(service, 'recovery_wait', wait, raising=False)
    store, w = setup_run(tmp_path, files=2)
    seen = Counter()
    bad = []
    def provider(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        bad[:] = bad or [ctx['items'][0]['part']['part_id']]
        items = []
        for item in ctx['items']:
            pid = item['part']['part_id']
            seen[pid] += 1
            if pid not in bad:
                items.append({'part_id': pid, 'coverage': 'no_operations'})
        return envelope(items)
    progress = []
    first = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider),
        cancelled=lambda: stopped[0], progress=lambda _, name: progress.append(name))
    assert first.status == 'cancelled' and waits and all(s > 0 for s in waits)
    assert any('Waiting to retry' in p and 'missing_extraction_item' in p for p in progress)
    before = analysis_report(store, w, first.run_id)['summary']['recovery_queue']
    assert before[bad[0]]['failures'] == 1
    assert not store.rows('SELECT * FROM analysis_runs')
    store.close()
    store = Store(tmp_path)
    stopped[0] = False
    def advance(seconds, check):
        # Readiness is based on persisted wall time; simulate reaching it.
        monkeypatch.setattr(service, 'time', lambda: before[bad[0]]['not_before'] + 1)
        check()
    monkeypatch.setattr(service, 'recovery_wait', advance)
    def fixed(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        assert [i['part']['part_id'] for i in ctx['items']] == bad
        assert ctx['items'][0]['validation_feedback']['attempt'] == 1
        return envelope([{'part_id': bad[0], 'coverage': 'no_operations'}])
    resumed = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id),
        transport=httpx.MockTransport(fixed))
    assert resumed.status == 'committed', resumed.reasons
    assert resumed.counts['requests'] == 2
    assert len(store.rows('SELECT * FROM analysis_runs')) == 1
    store.close()


def test_packing_fills_smaller_items_after_nonfitting_candidate_and_explains_budget():
    profile = model().model_copy(update={'max_tokens': 2000})
    sources = [replace(source(code), file_id=str(n)) for n, code in enumerate(['x' * 2000, 'y' * 2000, 'select 1;'])]
    parts = [plan_file_parts(s, {}, profile)[0] for s in sources]
    planned = pack_request(parts, profile, {'sources': {s.file_id: s for s in sources}})
    assert planned.part_ids == (parts[0].part_id, parts[2].part_id)
    assert planned.packing['stop_reasons'] == ['expected_output_budget']
    assert 0 < planned.packing['input_utilization'] < 1
    assert planned.packing['expected_output_tokens'] <= planned.reserved_output == 2000


def test_exhausted_transport_pass_defers_behind_other_files_and_preserves_unknowns(tmp_path, monkeypatch):
    import dataforge.analysis_service as service
    clock = [1000.]
    monkeypatch.setattr(service, 'time', lambda: clock[0])
    monkeypatch.setattr(service, 'recovery_wait', lambda seconds, check: (clock.__setitem__(0, clock[0] + seconds), check()))
    profile = model().model_copy(update={'max_tokens': 1000, 'retries': 0, 'unknown_retries': 1})
    store, w = setup_run(tmp_path, files=3, profile=profile)
    calls = []
    def provider(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        pid = ctx['items'][0]['part']['part_id']
        calls.append(pid)
        if len(calls) == 1:
            raise httpx.ReadError('DO_NOT_PERSIST')
        return envelope([{'part_id': pid, 'coverage': 'no_operations'}])
    result = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider))
    assert result.status == 'committed' and not result.usage_known
    assert calls[0] == calls[-1] and len(set(calls[:3])) == 3
    assert [a['status'] for a in store.rows('SELECT status FROM ai_analysis_attempts')] == ['unknown', 'received', 'received', 'received']
    assert result.counts['requests'] == 4 and result.counts['reserved_output_tokens'] == 4000
    store.close()


def test_repeated_truncation_does_not_split_forever_and_preserves_ranges_after_reopen(tmp_path, monkeypatch):
    import dataforge.analysis_service as service
    from dataforge.ai_analysis_models import FilePart
    stopped = [False]
    def stop(seconds, check):
        stopped[0] = True
        check()
    monkeypatch.setattr(service, 'recovery_wait', stop)
    store, w = setup_run(tmp_path)
    calls = []
    def truncated(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        calls.append(ctx)
        return envelope('{"items":[', finish='length')
    first = run_analysis(store, w, AnalysisRequest(mode='ai'), cancelled=lambda: stopped[0],
        transport=httpx.MockTransport(truncated))
    assert first.status == 'cancelled'
    summary = analysis_report(store, w, first.run_id)['summary']
    children = sorted([FilePart.model_validate(p) for p in summary['parts']], key=lambda p: p.start_offset)
    assert len(children) == 2 and children[0].end_offset == children[1].start_offset
    assert children[0].start_offset == 0 and children[1].end_offset == 1009
    assert all(p.overlap for p in children)
    assert len(calls) <= 3
    assert not store.rows('SELECT * FROM analysis_runs')
    store.close()
    store = Store(tmp_path)
    stopped[0] = False
    monkeypatch.setattr(service, 'time', lambda: 1e12)
    def fixed(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        for item in ctx['items']:
            assert item['overlap'] and item['source']
        return envelope([{'part_id': i['part']['part_id'], 'coverage': 'no_operations'} for i in ctx['items']])
    done = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id), transport=httpx.MockTransport(fixed))
    assert done.status == 'committed' and done.counts['parts'] == 2
    assert not analysis_report(store, w, first.run_id)['summary']['recovery_queue']
    saved = sorted([p for p, _ in load_file_parts(store, w, first.run_id)], key=lambda p: p.start_offset)
    assert saved == children
    store.close()


@pytest.mark.parametrize('limit', ['attempt', 'output'])
def test_semantic_recovery_preserves_explicit_spending_ceiling_across_reopen(tmp_path, monkeypatch, limit):
    import dataforge.analysis_service as service
    monkeypatch.setattr(service, 'time', lambda: 1000.)
    # No next dispatch before the configured ceiling: advance only the due time.
    monkeypatch.setattr(service, 'recovery_wait', lambda seconds, check: monkeypatch.setattr(service, 'time', lambda: 2000.))
    store, w = setup_run(tmp_path)
    calls = []
    def bad(request):
        calls.append(1)
        return envelope([])
    request = AnalysisRequest(mode='ai', **({'max_provider_attempts': 1} if limit == 'attempt' else {'max_output_tokens_total': 8000}))
    first = run_analysis(store, w, request, transport=httpx.MockTransport(bad))
    assert first.status == 'awaiting_continuation' and len(calls) == 1
    assert first.reasons == ['run_attempt_ceiling_reached' if limit == 'attempt' else 'run_output_ceiling_reached']
    store.close()
    store = Store(tmp_path)
    second = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id), transport=httpx.MockTransport(bad))
    assert second.reasons == first.reasons and len(calls) == 1
    assert not store.rows('SELECT * FROM analysis_runs')
    store.close()


def test_corrective_feedback_near_input_limit_can_recover_instead_of_failing_planning(tmp_path, monkeypatch):
    import dataforge.analysis_service as service
    monkeypatch.setattr(service, 'time', lambda: 1000.)
    monkeypatch.setattr(service, 'recovery_wait', lambda seconds, check: monkeypatch.setattr(service, 'time', lambda: 2000.))
    store, w = setup_run(tmp_path, profile=model(24000))
    Importer(store, w).files([('large.sql', b'x' * 15000)], {'.sql'})
    failed = [False]
    def provider(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        items = []
        for item in ctx['items']:
            if not failed[0] and len(item['source']) > 2000:
                failed[0] = True
                continue
            items.append({'part_id': item['part']['part_id'], 'coverage': 'no_operations'})
        return envelope(items)
    result = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider))
    assert result.status == 'committed', result.reasons
    assert failed[0]
    assert any(d['code'] == 'missing_extraction_item' for r in analysis_report(store, w, result.run_id)['recent_requests']
               for d in r['details'].get('diagnostics', []))
    store.close()


def test_failed_consolidation_does_not_block_other_files_or_erase_initial_facts(tmp_path, monkeypatch):
    import dataforge.analysis_service as service
    stopped, bad_path = [False], []
    def stop(seconds, check):
        stopped[0] = True
        check()
    monkeypatch.setattr(service, 'recovery_wait', stop)
    store, w = setup_run(tmp_path, files=0, profile=model().model_copy(update={'max_tokens': 2000}))
    Importer(store, w).files([('a.sql', b'select 1;' + b' ' * 5000), ('b.sql', b'select 2;' + b' ' * 5000)], {'.sql'})
    calls = Counter()
    def provider(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        items = []
        for i in ctx['items']:
            p = i['part']
            calls[p['part_id']] += 1
            if p['work_kind'] == 'consolidation':
                bad_path[:] = bad_path or [i['path']]
                if i['path'] == bad_path[0] and not stopped[0]:
                    continue
                items.append({'part_id': p['part_id']})
            else:
                ref = {k: p[k] for k in ('file_id', 'content_hash', 'start_offset', 'end_offset')}
                items.append({'part_id': p['part_id'], 'coverage': 'complete', 'operations': [{
                    'operation_id': 'op', 'kind': 'SELECT', 'evidence': [ref], 'reads': [{'name': 'raw'}], 'writes': [{'name': 'out'}]}]})
        return envelope(items)
    first = run_analysis(store, w, AnalysisRequest(mode='ai'), cancelled=lambda: stopped[0], transport=httpx.MockTransport(provider))
    assert first.status == 'cancelled'
    saved = load_file_parts(store, w, first.run_id)
    other = next(f['file_id'] for f in store.files(w) if f['relative_path'] != bad_path[0])
    assert any(p.work_kind == 'consolidation' and p.file_id == other for p, _ in saved)
    initial = [(p, r) for p, r in saved if p.work_kind == 'extraction']
    assert initial and all(r.operations for _, r in initial)
    assert not store.rows('SELECT * FROM analysis_runs')
    store.close()
    store = Store(tmp_path)
    stopped[0] = False
    monkeypatch.setattr(service, 'time', lambda: 1e12)
    bad_path.clear()
    def fixed(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        assert all(i['part']['work_kind'] == 'consolidation' for i in ctx['items'])
        assert all(i['part']['part_id'] not in {p.part_id for p, _ in saved} for i in ctx['items'])
        return envelope([{'part_id': i['part']['part_id']} for i in ctx['items']])
    done = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id), transport=httpx.MockTransport(fixed))
    assert done.status == 'committed'
    assert all(record in load_file_parts(store, w, first.run_id) for record in initial)
    assert len(store.rows('SELECT * FROM analysis_runs')) == 1
    store.close()


@pytest.mark.parametrize('usage', [None, [], 'DO_NOT_PERSIST', {'private': 2},
                                  {'prompt_tokens': -1, 'completion_tokens': -2}, {'prompt_tokens': 2}])
def test_non_object_usage_metadata_does_not_crash_or_claim_known_usage(tmp_path, usage):
    store, w = setup_run(tmp_path)
    def provider(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        response = envelope([{'part_id': i['part']['part_id']} for i in ctx['items']])
        body = response.json()
        body['usage'] = usage
        return httpx.Response(200, json=body)
    result = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider))
    assert result.status == 'committed' and not result.usage_known
    assert 'DO_NOT_PERSIST' not in json.dumps(store.rows('SELECT details FROM ai_analysis_attempts'))
    store.close()


def test_resume_keeps_pinned_definitions_when_feedback_reserve_changes_part_plan(tmp_path, monkeypatch):
    import dataforge.ai_batching as batching
    import dataforge.analysis_service as service
    reserve = batching.RECOVERY_FEEDBACK_RESERVE
    monkeypatch.setattr(batching, 'RECOVERY_FEEDBACK_RESERVE', {})  # Existing checkpoint's fitting behavior.
    stopped = [False]
    def stop(seconds, check):
        stopped[0] = True
        check()
    monkeypatch.setattr(service, 'recovery_wait', stop)
    store, w = setup_run(tmp_path, files=0, profile=model(24000))
    Importer(store, w).files([('consumer.sql', b'select * from x where ' + b'x' * 15000),
                              ('definition.sql', b'create table x as select 1 as id;')], {'.sql'})
    pinned = {}
    def initial(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        items = []
        for i in ctx['items']:
            if i['path'] == 'consumer.sql':
                pinned[i['part']['part_id']] = i['part']
                continue
            items.append({'part_id': i['part']['part_id'], 'coverage': 'no_operations'})
        return envelope(items)
    first = run_analysis(store, w, AnalysisRequest(mode='ai'), cancelled=lambda: stopped[0], transport=httpx.MockTransport(initial))
    assert first.status == 'cancelled' and any(p['context_ids'] for p in pinned.values())
    store.close()
    monkeypatch.setattr(batching, 'RECOVERY_FEEDBACK_RESERVE', reserve)
    stopped[0] = False
    monkeypatch.setattr(service, 'time', lambda: 1e12)
    store = Store(tmp_path)
    planned_ids = {p.part_id for p in service._prepare(store, w, AnalysisRequest(mode='ai'))[1]}
    assert any(pid not in planned_ids and p['context_ids'] for pid, p in pinned.items())
    definitions_seen = []
    def fixed(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        for i in ctx['items']:
            ids = set(i['part']['context_ids'])
            if ids:
                supplied = {d['entry_id'] for d in ctx['definitions']}
                assert ids <= supplied, 'Resume omitted the original pinned definition'
                definitions_seen.extend(ids)
        return envelope([{'part_id': i['part']['part_id'], 'coverage': 'no_operations'} for i in ctx['items']])
    done = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id), transport=httpx.MockTransport(fixed))
    assert done.status == 'committed' and definitions_seen
    store.close()


def test_legacy_completed_consolidation_groups_do_not_repartition_or_repeat_supersession(tmp_path, monkeypatch):
    from math import ceil

    import dataforge.ai_batching as batching
    import dataforge.analysis_service as service
    from dataforge.model_capabilities import ModelCapabilities, bind_capabilities
    profile = model()
    profile.model_capabilities = bind_capabilities(ModelCapabilities(input_tokens=ceil(13350 / .95),
        window='separate', source='manual'), profile)
    reserve = batching.RECOVERY_FEEDBACK_RESERVE
    monkeypatch.setattr(batching, 'RECOVERY_FEEDBACK_RESERVE', {})
    store, w = setup_run(tmp_path, files=0, profile=profile)
    Importer(store, w).files([('q.sql', b'x' * 6000)], {'.sql'})
    calls = []
    def provider(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        items = []
        for i in ctx['items']:
            p = i['part']
            calls.append((p['work_kind'], p['part_id']))
            item = {'part_id': p['part_id'], 'coverage': 'complete'}
            if p['work_kind'] == 'extraction':
                ref = {k: p[k] for k in ('file_id', 'content_hash', 'start_offset', 'end_offset')}
                ops = [{'operation_id': 'op', 'kind': 'SELECT', 'evidence': [ref],
                    'reads': [{'name': f'raw{p["part_index"]}'}], 'writes': [{'name': f'out{p["part_index"]}'}]}]
            else:
                original = i['saved_details']['operations']
                evidence = {json.dumps(r, sort_keys=True): r for op in original for r in op['evidence']}
                ops = [{'operation_id': 'merged', 'kind': 'MERGED', 'evidence': list(evidence.values()),
                    'reads': [r for op in original for r in op['reads']], 'writes': [r for op in original for r in op['writes']]}]
                item['superseded_operation_ids'] = [op['operation_id'] for op in original]
            item['operations'] = ops
            items.append(item)
        return envelope(items)
    save_file = service.save_file_extraction
    def interrupted(*args, **kwargs):
        raise ValueError('synthetic_before_publication')
    monkeypatch.setattr(service, 'save_file_extraction', interrupted)
    first = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider))
    assert first.status == 'failed'
    assert sum(kind == 'consolidation' for kind, _ in calls) == 2
    summary = analysis_report(store, w, first.run_id)['summary']
    # Simulate a checkpoint written before recovery/group plans were pinned.
    summary.pop('consolidation_work', None)
    summary.pop('recovery_protocol', None)
    store.execute('UPDATE ai_analysis_runs SET summary=? WHERE run_id=?', [json.dumps(summary), first.run_id])
    before = list(calls)
    store.close()
    monkeypatch.setattr(batching, 'RECOVERY_FEEDBACK_RESERVE', reserve)
    monkeypatch.setattr(service, 'save_file_extraction', save_file)
    store = Store(tmp_path)
    done = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id), transport=httpx.MockTransport(provider))
    assert done.status == 'committed', done.reasons
    assert calls == before
    assert len(store.rows('SELECT * FROM analysis_runs')) == 1
    store.close()


def test_interrupted_group_planning_does_not_freeze_an_incomplete_work_list(tmp_path, monkeypatch):
    import dataforge.analysis_service as service
    store, w = setup_run(tmp_path, files=0, profile=model().model_copy(update={'max_tokens': 2000}))
    Importer(store, w).files([('a.sql', b'x' * 5000), ('b.sql', b'y' * 5000)], {'.sql'})
    consolidation_files = set()
    def provider(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        items = []
        for i in ctx['items']:
            p = i['part']
            item = {'part_id': p['part_id']}
            if p['work_kind'] == 'extraction':
                ref = {k: p[k] for k in ('file_id', 'content_hash', 'start_offset', 'end_offset')}
                item['operations'] = [{'operation_id': 'op', 'kind': 'CREATE', 'evidence': [ref],
                    'writes': [{'name': f'out{p["part_index"]}'}]}]
            else:
                consolidation_files.add(i['path'])
            items.append(item)
        return envelope(items)
    planner = service.plan_file_consolidation
    plans = []
    def interrupted(*args, **kwargs):
        plans.append(1)
        if len(plans) == 2:
            raise ValueError('synthetic_interrupted_group_plan')
        return planner(*args, **kwargs)
    monkeypatch.setattr(service, 'plan_file_consolidation', interrupted)
    first = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider))
    assert first.status == 'failed' and not consolidation_files
    monkeypatch.setattr(service, 'plan_file_consolidation', planner)
    resumed = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id), transport=httpx.MockTransport(provider))
    assert resumed.status == 'committed'
    assert consolidation_files == {'a.sql', 'b.sql'}
    store.close()


@pytest.mark.parametrize('cutoff', [False, True])
def test_truncated_batch_commits_valid_siblings_and_retries_only_missing(tmp_path, monkeypatch, cutoff):
    from test_ai_partial_recovery import advance_backoff
    advance_backoff(monkeypatch)
    store, w = setup_run(tmp_path, files=3)
    seen, calls = Counter(), []
    def provider(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        ids = [i['part']['part_id'] for i in ctx['items']]
        seen.update(ids)
        calls.append(ids)
        items = [{'part_id': p, 'coverage': 'no_operations'} for p in ids]
        if len(calls) == 1:
            content = json.dumps({'items': items[:2]})
            if cutoff:
                content = content[:-2] + ',{"part_id":' + json.dumps(ids[2]) + ',"coverage":"no_'
            return envelope(content, finish='length')
        return envelope(items)
    result = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider))
    assert result.status == 'committed', result.reasons
    assert len(calls[0]) == 3 and calls[1:] == [[calls[0][2]]]
    assert [seen[p] for p in calls[0]] == [1, 1, 2]
    assert len(load_file_parts(store, w, result.run_id)) == 3
    store.close()


def test_complete_truncated_response_keeps_visible_warning(tmp_path):
    store, w = setup_run(tmp_path)
    def provider(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        return envelope([{'part_id': i['part']['part_id'], 'coverage':'no_operations'} for i in ctx['items']], finish='length')
    result = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider))
    assert result.status == 'committed'
    diagnostics = [d for r in store.rows('SELECT details FROM ai_analysis_requests') for d in json.loads(r['details'])['diagnostics']]
    assert any(d['code'] == 'truncated_extraction_response' and d['recovery_action'] == 'complete_items_preserved' for d in diagnostics)
    store.close()
