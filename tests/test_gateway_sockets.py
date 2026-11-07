import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from test_gateway_recovery import setup_run

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.analysis_service import run_analysis


@contextmanager
def gateway(mode, delay=.35):
    calls, release = [], threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(time.monotonic())
            ctx = json.loads(body['messages'][-1]['content'])
            payload = json.dumps({'choices': [{'message': {'content': json.dumps({'items': [
                {'part_id': i['part']['part_id'], 'coverage': 'no_operations'} for i in ctx['items']]})}}]}).encode()
            if mode == 'silent' or (mode == 'timeout' and len(calls) == 1):
                release.wait(5)
            elif mode in {'delay', 'fallback'}:
                # Simulate upstream time spent inside one gateway request. The
                # application cannot infer a real provider switch from this wait.
                release.wait(delay / 2)
                release.wait(delay / 2)
            try:
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                if mode == 'partial' and len(calls) == 1:
                    self.wfile.write(payload[:10])
                    self.wfile.flush()
                    self.close_connection = True
                else:
                    self.wfile.write(payload)
            except (OSError, ConnectionError):
                pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', calls
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(2)


def set_endpoint(store, w, url, read):
    from dataforge.llm import Profile
    from dataforge.model_capabilities import bind_capabilities
    row = store.rows('SELECT profile_id,config FROM llm_profiles')[0]
    profile = Profile.model_validate(json.loads(row['config']))
    capabilities = profile.model_capabilities
    profile = profile.model_copy(update={'base_url': url, 'read_timeout': read})
    profile.model_capabilities = bind_capabilities(capabilities, profile)
    store.execute('UPDATE llm_profiles SET config=? WHERE profile_id=?', [profile.model_dump_json(), row['profile_id']])


@pytest.mark.parametrize('mode', ['delay', 'fallback', 'timeout', 'partial'])
def test_real_gateway_wait_or_bounded_retry(tmp_path, mode):
    store, w = setup_run(tmp_path)
    with gateway(mode) as (url, calls):
        set_endpoint(store, w, url, 1 if mode in {'delay', 'fallback'} else .15)
        result = run_analysis(store, w, AnalysisRequest(mode='ai'))
        assert result.status == 'committed', result.reasons
        assert len(calls) == (1 if mode in {'delay', 'fallback'} else 2)
        statuses = [a['status'] for a in store.rows('SELECT status FROM ai_analysis_attempts')]
        assert statuses == (['received'] if len(calls) == 1 else ['unknown', 'received'])
    store.close()


@pytest.mark.parametrize('stop', ['cancel', 'deadline'])
@pytest.mark.parametrize('unlimited', [False, True])
def test_silent_socket_is_interrupted_without_waiting_for_read_timeout(tmp_path, monkeypatch, stop, unlimited):
    store, w = setup_run(tmp_path)
    start = time.monotonic()
    with gateway('silent') as (url, calls):
        if stop == 'deadline':
            def deadline_clock():
                now = time.monotonic()
                # Accelerate the silent socket, not preparation on slower runners.
                return now + ((now - calls[0]) * 199 if calls else 0)
            monkeypatch.setattr('dataforge.analysis_service.monotonic', deadline_clock)
        set_endpoint(store, w, url, 5)
        if unlimited:
            row = store.rows('SELECT profile_id,config FROM llm_profiles')[0]
            config = json.loads(row['config'])
            config['wait_until_stopped'] = True
            store.execute('UPDATE llm_profiles SET config=? WHERE profile_id=?', [json.dumps(config), row['profile_id']])
        def slow_preparation(_fraction, activity):
            if stop == 'deadline' and activity == 'Preparing selected sources':
                time.sleep(.2)
        result = run_analysis(store, w, AnalysisRequest(mode='ai', max_seconds=30 if stop == 'deadline' else None),
            progress=slow_preparation,
            cancelled=(lambda: bool(calls) and time.monotonic() - calls[0] > .2) if stop == 'cancel' else None)
        assert result.status == ('cancelled' if stop == 'cancel' else 'awaiting_continuation'), result.reasons
        assert time.monotonic() - start < 2
        assert len(calls) == 1
        assert store.rows('SELECT status FROM ai_analysis_attempts')[0]['status'] == 'unknown'
        assert not result.usage_known
    store.close()


@pytest.mark.parametrize('mode', ['fallback', 'partial', 'silent'])
def test_wait_until_stopped_keeps_slow_request_and_cancellation(tmp_path, mode):
    store, w = setup_run(tmp_path)
    with gateway(mode, delay=.4) as (url, calls):
        set_endpoint(store, w, url, .05)
        row = store.rows('SELECT profile_id,config FROM llm_profiles')[0]
        config = json.loads(row['config'])
        config['wait_until_stopped'] = True
        store.execute('UPDATE llm_profiles SET config=? WHERE profile_id=?', [json.dumps(config), row['profile_id']])
        started = time.monotonic()
        result = run_analysis(store, w, AnalysisRequest(mode='ai'),
            cancelled=(lambda: bool(calls) and time.monotonic() - calls[0] > .2) if mode == 'silent' else None)
        assert result.status == ('cancelled' if mode == 'silent' else 'committed'), result.reasons
        assert len(calls) == (2 if mode == 'partial' else 1)
        assert time.monotonic() - started < 3
        attempts = store.rows('SELECT status,details FROM ai_analysis_attempts')
        assert all(json.loads(a['details'])['timeouts']['read'] is None for a in attempts)
        if mode == 'partial':
            assert json.loads(attempts[0]['details'])['transport_error'] == 'RemoteProtocolError'
    store.close()
