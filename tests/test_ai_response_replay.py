"""Replay contract: isolated DuckDB and synthetic provider envelopes only."""
import json

import httpx
import pytest
from test_ai_extraction_recovery import envelope
from test_ai_inspection import setup_run
from test_ai_resumable_files import empty_provider

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_analysis_store import load_file_parts
from dataforge.ai_pipeline_store import attempt_totals
from dataforge.analysis_service import run_analysis
from dataforge.store import Store


@pytest.mark.parametrize('after', [0, 1])
def test_crash_replay_reuses_response_without_dispatch_or_usage_increment(tmp_path, monkeypatch, after):
    import dataforge.analysis_service as service
    store, w = setup_run(tmp_path, files=3)
    seen, saved = [], []
    save = service.save_part_extraction
    finish = service.finish_attempt
    def interrupted_save(*args, **kwargs):
        save(*args, **kwargs)
        saved.append(args[3].part_id)
        if len(saved) == after:
            raise OSError('synthetic interruption after durable save')
    def interrupted_finish(*args, **kwargs):
        finish(*args, **kwargs)
        if after == 0 and args[4] == 'received':
            raise OSError('synthetic interruption at receipt')
    with monkeypatch.context() as patch:
        patch.setattr(service, 'save_part_extraction', interrupted_save)
        patch.setattr(service, 'finish_attempt', interrupted_finish)
        first = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(empty_provider(seen)))
    assert first.status == 'failed'
    assert len(load_file_parts(store, w, first.run_id)) == after
    totals = attempt_totals(store, w, first.run_id)
    store.close()
    store = Store(tmp_path)
    replayed = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id),
        transport=httpx.MockTransport(lambda r: pytest.fail('replay dispatched provider')))
    assert replayed.status == 'committed', replayed.reasons
    assert attempt_totals(store, w, first.run_id) == totals
    assert replayed.counts['input_tokens'] == replayed.counts['output_tokens'] == 1
    assert len(load_file_parts(store, w, first.run_id)) == 3
    assert store.rows('SELECT status FROM ai_analysis_requests') == [{'status': 'processed'}]
    store.close()


@pytest.mark.parametrize('fault', ['history_off', 'redacted', 'corrupt'])
def test_unavailable_response_never_replays_or_silently_resends(tmp_path, monkeypatch, fault):
    import dataforge.analysis_service as service
    from dataforge.ai_inspection import load_replayable_response
    store, w = setup_run(tmp_path)
    if fault == 'history_off':
        store.set_setting(w, 'llm_history', False)
    finish = service.finish_attempt
    def interrupt(*args, **kwargs):
        finish(*args, **kwargs)
        if args[4] == 'received':
            raise OSError('crash')
    with monkeypatch.context() as patch:
        patch.setattr(service, 'finish_attempt', interrupt)
        first = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(
            lambda r: envelope([{'part_id': json.loads(json.loads(r.content)['messages'][-1]['content'])['items'][0]['part']['part_id'], 'coverage':'no_operations'}])))
    a = store.rows('SELECT * FROM ai_analysis_attempts')[0]
    fingerprint = json.loads(store.rows('SELECT details FROM ai_analysis_requests')[0]['details'])['fingerprint']
    if fault == 'redacted':
        store.execute('UPDATE ai_inspection_artifacts SET redacted=true')
    elif fault == 'corrupt':
        store.execute("UPDATE ai_inspection_artifacts SET content='{}'")
    loaded = load_replayable_response(store, w, first.run_id, a['attempt_id'], expected_fingerprint=fingerprint)
    assert loaded['content'] is None and loaded['reason']
    second = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id),
        transport=httpx.MockTransport(lambda r: pytest.fail('unavailable response resent')))
    assert second.reasons == ['unknown_inflight_request_requires_explicit_retry']
    store.close()


def test_response_capture_failure_blocks_dispatch_and_advertisement(tmp_path, monkeypatch):
    import dataforge.analysis_service as service
    store, w = setup_run(tmp_path)
    capture = service.capture_payload
    def fail(*args, **kwargs):
        if args[4] == 'output':
            raise OSError('response storage unavailable')
        return capture(*args, **kwargs)
    monkeypatch.setattr(service, 'capture_payload', fail)
    seen = []
    result = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(empty_provider(seen)))
    assert result.status == 'failed' and len(seen) == 1
    assert not load_file_parts(store, w, result.run_id)
    assert 'response_checkpoint' not in store.rows('SELECT details FROM ai_analysis_attempts')[0]['details']
    store.close()


def test_crash_after_wire_checkpoint_recovers_received_usage(tmp_path, monkeypatch):
    import dataforge.analysis_service as service
    store, w = setup_run(tmp_path)
    capture = service.capture_payload
    def crash(*args, **kwargs):
        capture(*args, **kwargs)
        if args[4] == 'output':
            raise OSError('after wire checkpoint before received outcome')
    with monkeypatch.context() as patch:
        patch.setattr(service, 'capture_payload', crash)
        first = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(empty_provider([])))
    assert first.status == 'failed' and store.rows('SELECT status FROM ai_analysis_attempts') == [{'status':'dispatched'}]
    store.close()
    store = Store(tmp_path)
    second = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id),
        transport=httpx.MockTransport(lambda r: pytest.fail('wire checkpoint replay dispatched')))
    assert second.status == 'committed' and second.usage_known
    assert second.counts['input_tokens'] == second.counts['output_tokens'] == 1
    assert second.counts['requests'] == 1
    store.close()
