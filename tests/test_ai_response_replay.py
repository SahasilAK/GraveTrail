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


@pytest.mark.parametrize('after', [0, 1, 2, 3])
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


@pytest.mark.parametrize('fault', ['history_off', 'disabled_later', 'expired', 'redacted', 'missing', 'corrupt', 'historical', 'context', 'oversized', 'workspace', 'run'])
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
        if fault == 'oversized':
            patch.setattr('dataforge.ai_inspection.MAX_ARTIFACT_BYTES', 100)
        first = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(
            lambda r: envelope([{'part_id': json.loads(json.loads(r.content)['messages'][-1]['content'])['items'][0]['part']['part_id'], 'coverage':'no_operations'}])))
    a = store.rows('SELECT * FROM ai_analysis_attempts')[0]
    fingerprint = json.loads(store.rows('SELECT details FROM ai_analysis_requests')[0]['details'])['fingerprint']
    if fault == 'disabled_later':
        store.set_setting(w, 'llm_history', False)
    elif fault == 'expired':
        store.execute('UPDATE ai_inspection_artifacts SET captured_at=0')
    elif fault == 'redacted':
        store.execute('UPDATE ai_inspection_artifacts SET redacted=true')
    elif fault == 'missing':
        store.execute('DELETE FROM ai_inspection_artifacts')
    elif fault == 'corrupt':
        store.execute("UPDATE ai_inspection_artifacts SET content='{}'")
    elif fault == 'historical':
        store.execute("UPDATE ai_analysis_attempts SET details='{}'")
    elif fault == 'context':
        fingerprint = 'wrong-context'
    loaded = load_replayable_response(store, 'wrong' if fault == 'workspace' else w,
        'wrong' if fault == 'run' else first.run_id, a['attempt_id'], expected_fingerprint=fingerprint)
    assert loaded['content'] is None and loaded['reason']
    if fault not in {'context', 'workspace', 'run'}:
        second = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id),
            transport=httpx.MockTransport(lambda r: pytest.fail('unavailable response resent')))
        assert second.reasons == (['source_or_configuration_changed'] if fault == 'disabled_later' else
            ['unknown_inflight_request_requires_explicit_retry'])
    store.close()


def test_retention_cleanup_keeps_validated_parts_and_backup_replays(tmp_path, monkeypatch):
    import dataforge.analysis_service as service
    from dataforge.ai_inspection import cleanup_payloads, load_replayable_response
    from dataforge.database_maintenance import backup, restore_backup
    store, w = setup_run(tmp_path / 'original', files=3)
    save = service.save_part_extraction
    def interrupt(*args, **kwargs):
        save(*args, **kwargs)
        raise OSError('after first save')
    with monkeypatch.context() as patch:
        patch.setattr(service, 'save_part_extraction', interrupt)
        first = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(empty_provider([])))
    archive = backup(store)
    a = store.rows('SELECT attempt_id FROM ai_analysis_attempts')[0]['attempt_id']
    fingerprint = json.loads(store.rows('SELECT details FROM ai_analysis_requests')[0]['details'])['fingerprint']
    store.execute('UPDATE ai_inspection_artifacts SET captured_at=0')
    cleanup_payloads(store, w)
    assert len(load_file_parts(store, w, first.run_id)) == 1
    assert load_replayable_response(store, w, first.run_id, a, expected_fingerprint=fingerprint)['content'] is None
    store.close()
    restored = tmp_path / 'restored'
    restore_backup(archive, restored)
    store = Store(restored)
    result = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id),
        transport=httpx.MockTransport(lambda r: pytest.fail('restored replay sent provider request')))
    assert result.status == 'committed' and len(load_file_parts(store, w, first.run_id)) == 3
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


def test_history_off_complete_parts_need_no_response_retry_acknowledgement(tmp_path, monkeypatch):
    import dataforge.analysis_service as service
    store, w = setup_run(tmp_path, files=3)
    store.set_setting(w, 'llm_history', False)
    save = service.save_part_extraction
    count = []
    def interrupted(*args, **kwargs):
        save(*args, **kwargs)
        count.append(1)
        if len(count) == 3:
            raise OSError('crash before request finalization')
    with monkeypatch.context() as patch:
        patch.setattr(service, 'save_part_extraction', interrupted)
        first = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(empty_provider([])))
    assert first.status == 'failed'
    store.close()
    store = Store(tmp_path)
    result = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id),
        transport=httpx.MockTransport(lambda r: pytest.fail('completed work dispatched')))
    assert result.status == 'committed', result.reasons
    assert result.usage_known
    assert store.rows('SELECT status FROM ai_analysis_requests') == [{'status': 'processed'}]
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
