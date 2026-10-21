import json
import threading
import time

import httpx

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_analysis_store import save_run
from dataforge.ai_context import AIExecutionContext, plan_ai_units, prepare_analysis
from dataforge.ingestion import Importer
from dataforge.llm import Profile
from dataforge.store import Store


def test_parallel_workers_never_access_store_and_batch_items_survive_partial_response(tmp_path):
    from dataforge.ai_scheduler import run_pending_requests
    store = Store(tmp_path)
    w = store.create_workspace('scheduler')
    Importer(store, w).files([(f'{i}.sql', f'select {i};'.encode()) for i in range(5)], {'.sql'})
    p = Profile(provider='OpenAI compatible', base_url='http://localhost:1234', model='m',
                retries=0, max_tokens=8192, context_chars=100000)
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', w, 'm', p.model_dump_json()])
    store.set_setting(w, 'default_profile', 'p')
    store.set_setting(w, 'max_context_chars', 100000)
    store.set_setting(w, 'llm_concurrency', 2)
    request = AnalysisRequest(mode='ai', max_files_per_request=2, max_parallel_requests=2)
    plan = plan_ai_units(prepare_analysis(store, w, request))
    active, peak = [0], [0]
    lock = threading.Lock()
    sent = []
    def provider(r):
        body = json.loads(r.content)
        context = json.loads(body['messages'][1]['content'][body['messages'][1]['content'].find('{'):])
        units = [x['unit'] for x in context['items']] if 'items' in context else [context['unit']]
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            sent.extend(u['unit_id'] for u in units)
        time.sleep(.03)
        result = [{'unit_id': u['unit_id'], 'coverage': {'status': 'partial'}} for u in units]
        if len(sent) <= 2 and len(result) == 2:
            result = result[:1]
        payload = {'items': result} if 'items' in context else result[0]
        with lock:
            active[0] -= 1
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(payload)}, 'finish_reason': 'stop'}]})
    e = AIExecutionContext(request, transport=httpx.MockTransport(provider))
    e.project_allowance = {'max_provider_attempts': 100, 'max_output_tokens_total': 1000000, 'max_seconds': 1000}
    save_run(store, w, 'run', mode='ai')
    owner = threading.get_ident()
    real_rows = store.rows
    def rows(*a, **k):
        assert threading.get_ident() == owner, 'worker accessed DuckDB'
        return real_rows(*a, **k)
    store.rows = rows
    accepted = []
    run_pending_requests(store, w, 'run', plan.units, e,
        contexts={u.unit_id: plan.context_for(u) for u in plan.units},
        accept=lambda u, response, record: accepted.append(u.unit_id))
    assert len(accepted) == len(set(accepted)) == 5
    assert peak[0] == 2
    assert len(store.rows('SELECT * FROM ai_analysis_attempts')) == e.attempts
    assert not store.rows("SELECT * FROM ai_analysis_attempts WHERE status='dispatched'")
    store.close()
