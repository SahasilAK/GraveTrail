"""Recovery uses mock responses, never provider/model accuracy as an oracle."""
import json
from collections import Counter

import httpx
import pytest
from test_ai_resumable_files import configured
from test_ai_token_budget import model

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_analysis_store import load_file_parts
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


@pytest.mark.parametrize('fault,code', [('unknown', 'missing_extraction_item'),
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
