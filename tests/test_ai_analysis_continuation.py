import json

import httpx
import pytest
from test_ai_resumable_files import configured

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.analysis_service import run_analysis
from dataforge.ingestion import Importer
from dataforge.store import Store


@pytest.mark.parametrize('change', ['source', 'configuration', 'prompt'])
def test_resume_rejects_changed_inputs_before_dispatch(tmp_path, monkeypatch, change):
    store = Store(tmp_path)
    w = store.create_workspace('freshness')
    configured(store, w)
    Importer(store, w).files([('a.sql', b'select 1;')], {'.sql'})
    calls = []
    def lost(request):
        calls.append(1)
        raise httpx.ReadTimeout('lost')
    first = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(lost))
    assert first.status == 'awaiting_continuation'
    if change == 'source':
        Importer(store, w).files([('a.sql', b'select 2;')], {'.sql'})
    elif change == 'configuration':
        store.set_setting(w, 'case_sensitive', True)
    else:
        monkeypatch.setattr('dataforge.analysis_service._protocol_hash', lambda: 'upgraded')
    resumed = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id, retry_unknown=True),
                           transport=httpx.MockTransport(lost))
    assert resumed.status == 'stale', resumed.reasons
    assert len(calls) == 1
    store.close()


def test_historical_pause_cannot_be_hydrated_as_new_protocol(tmp_path):
    from dataforge.ai_analysis_store import save_run
    store = Store(tmp_path)
    w = store.create_workspace('legacy')
    save_run(store, w, 'old', mode='ai', status='awaiting_continuation', summary={'request': {'mode': 'ai'}})
    result = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id='old'))
    assert result.status == 'blocked'
    assert result.reasons == ['Legacy analysis checkpoint is incompatible; start a new build']
    assert json.loads(store.rows('SELECT summary FROM ai_analysis_runs')[0]['summary']) == {'request': {'mode': 'ai'}}
    store.close()
