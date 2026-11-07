from email.utils import formatdate


def test_retry_after_seconds_date_and_bad_values():
    from dataforge.ai_rate_limits import normalize_rate_limits, retry_delay
    assert normalize_rate_limits('Anthropic', {'retry-after': '90'}, now=100)['wait_until'] == 190
    assert normalize_rate_limits('Anthropic', {'Retry-After': formatdate(200, usegmt=True)}, now=100)['wait_until'] == 200
    assert retry_delay(0, {}, now=100, jitter=0) == 1
    assert retry_delay(12, {}, now=100, jitter=0) == 60
    assert retry_delay(0, {'retry-after': '90'}, now=100, jitter=0) == 90
    assert retry_delay(0, {'retry-after': 'nan'}, now=100, jitter=0) == 1


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
