

def test_retry_and_credit_exhaustion_use_durable_attempts(tmp_path, monkeypatch):
    import httpx
    from test_ai_resumable_files import configured, empty_provider
    from test_ai_token_budget import model

    from dataforge.ai_analysis_models import AnalysisRequest
    from dataforge.analysis_service import run_analysis
    from dataforge.ingestion import Importer
    from dataforge.store import Store
    store = Store(tmp_path)
    workspace = store.create_workspace('rate feedback')
    configured(store, workspace, model().model_copy(update={'retries': 1}))
    Importer(store, workspace).files([('a.sql', b'select 1;')], {'.sql'})
    calls, waits = [], []
    good = empty_provider([])
    def throttled(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={'retry-after': '3'})
        return good(request)
    monkeypatch.setattr('dataforge.llm.Adapter._wait', lambda self, seconds: waits.append(seconds))
    result = run_analysis(store, workspace, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(throttled))
    assert result.status == 'committed'
    assert result.counts['requests'] == 2 and waits == [3]
    credits = run_analysis(store, workspace, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(
        lambda request: httpx.Response(429, json={'error': {'code': 'insufficient_quota'}})))
    assert credits.status == 'awaiting_continuation'
    assert credits.reasons == ['provider_credits_exhausted']
    assert credits.counts['requests'] == 1
    store.close()
