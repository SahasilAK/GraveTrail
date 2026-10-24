import json
from collections import Counter

import httpx
import pytest
from test_ai_extraction_recovery import envelope, setup_run
from test_ai_resumable_files import configured
from test_ai_token_budget import model

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_analysis_store import load_file_extractions, load_file_parts
from dataforge.analysis_service import analysis_report, recovery_message, run_analysis
from dataforge.ingestion import Importer
from dataforge.store import Store


def advance_backoff(monkeypatch):
    import dataforge.analysis_service as service
    clock = [1000.]
    monkeypatch.setattr(service, 'time', lambda: clock[0])
    def advance(seconds, check):
        clock[0] += seconds
        check()
    monkeypatch.setattr(service, 'recovery_wait', advance)


def test_deferred_work_does_not_claim_publication_before_commit():
    pending = {'unresolved_work': {'part': {'file_id': 'file'}},
        'status': 'cancelled', 'last_failure': {'failure_category': 'cancelled'}}
    message = recovery_message(pending)
    assert 'published' not in message.lower()
    assert 'cancelled' in message.lower() and 'saved progress' in message.lower()
    published = recovery_message({**pending, 'status': 'committed'})
    assert 'published with incomplete coverage' in published


def test_bounded_invalid_work_publishes_explicit_partial_and_retries_only_unresolved_after_reopen(tmp_path, monkeypatch):
    advance_backoff(monkeypatch)
    store, w = setup_run(tmp_path, files=2)
    seen, calls, bad = Counter(), [], []
    def provider(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        calls.append(ctx)
        bad[:] = bad or [ctx['items'][0]['part']['part_id']]
        items = []
        for i in ctx['items']:
            p = i['part']
            seen[p['part_id']] += 1
            if p['part_id'] in bad:
                continue
            ref = {k: p[k] for k in ('file_id', 'content_hash', 'start_offset', 'end_offset')}
            items.append({'part_id': p['part_id'], 'coverage': 'complete', 'operations': [{
                'operation_id': 'good', 'kind': 'CREATE', 'evidence': [ref], 'reads': [{'name': 'raw'}], 'writes': [{'name': 'good'}]}]})
        return envelope(items)
    first = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider),
        cancelled=lambda: len(calls) >= 5)  # Old infinite repair path fails by cancelling.
    assert first.status == 'committed' and 'required_work_unresolved' in first.reasons
    assert not first.complete and first.counts['unresolved_parts'] == first.counts['incomplete_files'] == 1
    assert first.counts['unprocessed_files'] == 1
    assert seen[bad[0]] == 3 and all(n == 1 for pid, n in seen.items() if pid not in bad)
    files = load_file_extractions(store, w, first.run_id)
    assert sum(not f.processed for f in files) == 1 and len(store.edges(w)) == 1
    failed = [r for r in store.rows('SELECT status,result FROM ai_analysis_units') if r['status'] == 'unresolved']
    assert len(failed) == 1 and json.loads(failed[0]['result'])['extraction']['coverage'] == 'partial'
    assert analysis_report(store, w, first.run_id)['summary']['unresolved_work']
    store.close()
    store = Store(tmp_path)
    assert analysis_report(store, w, first.run_id)['summary']['counts'] == first.counts
    def fixed(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        assert [i['part']['part_id'] for i in ctx['items']] == bad
        return envelope([{'part_id': bad[0], 'coverage': 'no_operations'}])
    second = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id), transport=httpx.MockTransport(fixed))
    assert second.status == 'committed' and 'required_work_unresolved' not in second.reasons
    assert second.counts['unresolved_parts'] == 0
    assert second.counts['unprocessed_files'] == 0
    assert all(f.processed for f in load_file_extractions(store, w, first.run_id))
    assert not analysis_report(store, w, first.run_id)['summary']['unresolved_work']
    assert len(store.edges(w)) == 1 and len(store.rows('SELECT * FROM analysis_runs')) == 2
    store.close()


def test_failed_completion_keeps_saved_initial_facts_and_is_retryable(tmp_path, monkeypatch):
    advance_backoff(monkeypatch)
    store = Store(tmp_path)
    w = store.create_workspace('partial enrichment')
    configured(store, w, model())
    Importer(store, w).files([('consumer.sas', b'%load;'), ('definition.sas', b'opaque load;')], {'.sas'})
    calls, seen = [], []
    def provider(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        calls.append(ctx)
        items = []
        for i in ctx['items']:
            p = i['part']
            seen.append(p['work_kind'])
            if p['work_kind'] == 'context_completion':
                continue
            ref = {k: p[k] for k in ('file_id', 'content_hash', 'start_offset', 'end_offset')}
            item = {'part_id': p['part_id'], 'coverage': 'complete'}
            if i['path'] == 'definition.sas':
                item['definitions'] = [{'entry_id': 'load', 'symbol': 'load', 'kind': 'macro', 'source_kind': 'sas',
                    'origin': 'ai_inferred', 'evidence': [ref]}]
            else:
                item['missing_context'] = [{'symbol': 'load', 'kind': 'macro'}]
            items.append(item)
        return envelope(items)
    first = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider), cancelled=lambda: len(calls) >= 6)
    assert first.status == 'committed' and first.counts['unresolved_parts'] == 1
    assert 'consolidation_work' not in analysis_report(store, w, first.run_id)['summary']
    initial = [(p, r) for p, r in load_file_parts(store, w, first.run_id) if p.work_kind == 'extraction']
    assert len(initial) == 2 and any(r.definitions for _, r in initial)
    assert any(r.missing_context for _, r in initial)
    def fixed(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        assert all(i['part']['work_kind'] == 'context_completion' for i in ctx['items'])
        return envelope([{'part_id': i['part']['part_id'], 'coverage': 'complete'} for i in ctx['items']])
    resumed = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id), transport=httpx.MockTransport(fixed))
    assert resumed.status == 'committed' and resumed.counts['unresolved_parts'] == 0
    assert all(row in load_file_parts(store, w, first.run_id) for row in initial)
    store.close()


def test_partly_successful_large_file_keeps_facts_ranges_and_later_consolidates_without_reextracting(tmp_path, monkeypatch):
    advance_backoff(monkeypatch)
    store, w = setup_run(tmp_path, files=0, profile=model().model_copy(update={'max_tokens': 2000}))
    Importer(store, w).files([('large.sql', b'x' * 9000)], {'.sql'})
    calls, bad = Counter(), []
    def provider(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        items = []
        for i in ctx['items']:
            p = i['part']
            assert p['work_kind'] == 'extraction'
            bad[:] = bad or [p['part_id']]
            calls[p['part_id']] += 1
            if p['part_id'] == bad[0]:
                continue
            ref = {k: p[k] for k in ('file_id', 'content_hash', 'start_offset', 'end_offset')}
            items.append({'part_id': p['part_id'], 'coverage': 'complete', 'operations': [{
                'operation_id': 'op', 'kind': 'CREATE', 'evidence': [ref],
                'reads': [{'name': 'raw'}], 'writes': [{'name': 'out' + str(p['start_offset'])}]}]})
        return envelope(items)
    first = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider),
        cancelled=lambda: sum(calls.values()) > 20)
    assert first.status == 'committed' and first.counts['unresolved_parts'] == 1
    initial = load_file_parts(store, w, first.run_id)
    parts = sorted([p for p, _ in initial], key=lambda p: p.start_offset)
    assert parts[0].start_offset == 0 and parts[-1].end_offset == 9000
    assert all(a.end_offset == b.start_offset for a, b in zip(parts, parts[1:]))
    file = load_file_extractions(store, w, first.run_id)[0]
    assert not file.processed and len(file.operations) == len(parts) - 1
    good_ids = {p.part_id for p, r in initial if r.operations}
    stages = []
    def fixed(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        for i in ctx['items']:
            p = i['part']
            stages.append(p['work_kind'])
            if p['work_kind'] == 'extraction':
                assert p['part_id'] == bad[0] and p['part_id'] not in good_ids
        return envelope([{'part_id': i['part']['part_id'], 'coverage': 'no_operations'} for i in ctx['items']])
    second = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id), transport=httpx.MockTransport(fixed))
    assert second.status == 'committed' and 'consolidation' in stages
    final = load_file_extractions(store, w, first.run_id)[0]
    assert final.processed and final.operations == file.operations
    store.close()


@pytest.mark.parametrize('change', ['source', 'configuration', 'publication'])
def test_partial_retry_does_not_bypass_freshness_or_another_publication(tmp_path, monkeypatch, change):
    advance_backoff(monkeypatch)
    store, w = setup_run(tmp_path)
    count = []
    def bad(request):
        count.append(1)
        return envelope([])
    first = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(bad), cancelled=lambda: len(count) > 4)
    assert first.status == 'committed'
    if change == 'source':
        Importer(store, w).files([('0.sql', b'select 99;')], {'.sql'})
    elif change == 'configuration':
        store.set_setting(w, 'case_sensitive', True)
    else:
        from dataforge.services import analyze
        analyze(store, w)
    retry = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id),
        transport=httpx.MockTransport(lambda r: pytest.fail('Stale retry sent source')))
    assert retry.status == 'stale'
    store.close()
