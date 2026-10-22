"""Actual 2,200-file context qualification. Mock execution proves orchestration, not model accuracy."""
from __future__ import annotations

import argparse
import json
import tempfile
import time
import zipfile
from contextlib import nullcontext
from pathlib import Path

import httpx

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_budget import request_allowance
from dataforge.analysis_service import preview_analysis, run_analysis
from dataforge.ingestion import Importer
from dataforge.llm import Profile
from dataforge.model_capabilities import ModelCapabilities, bind_capabilities
from dataforge.store import Store


def evaluate(*, execute=False, input_tokens=16384, fixture_home=None):
    root = Path(__file__).resolve().parents[1]
    files = []
    for name in ('banking_legacy_sql_2114_lineage_stress_test.zip', 'dataforge_sql_lineage_test_project.zip'):
        with zipfile.ZipFile(root / 'tests' / 'sample_data' / name) as archive:
            files.extend((name, archive.read(name)) for name in archive.namelist() if name.lower().endswith('.sql'))
    assert len(files) == 2200
    started = time.monotonic()
    if fixture_home is not None:
        fixture_home = Path(fixture_home).resolve()
        if fixture_home.parent != Path(tempfile.gettempdir()).resolve() or not fixture_home.name.startswith('gravetrail-fixture-context-'):
            raise ValueError('Only a task-owned temporary fixture home can be reused')
    home = nullcontext(fixture_home) if fixture_home else tempfile.TemporaryDirectory(prefix='gravetrail-fixture-context-')
    with home as folder:
        store = Store(folder)
        try:
            existing = store.rows('SELECT workspace_id,name FROM workspaces')
            if existing:
                assert len(existing) == 1 and existing[0]['name'] == 'actual 2200 SQL fixture qualification'
                w = existing[0]['workspace_id']
                assert len(store.files(w)) == 2200
            else:
                w = store.create_workspace('actual 2200 SQL fixture qualification')
                print('Importing 2,200 fixture files', flush=True)
                Importer(store, w).files(files, {'.sql'})
            print('Fixture import complete; checking complete request envelopes', flush=True)
            profile = Profile(provider='OpenAI compatible', base_url='http://localhost:1234', model='mock', retries=0)
            profile.model_capabilities = bind_capabilities(ModelCapabilities(context_tokens=input_tokens,
                input_tokens=input_tokens, output_tokens=4096), profile)
            store.execute('INSERT OR REPLACE INTO llm_profiles VALUES (?,?,?,?)', ['p', w, 'mock', profile.model_dump_json()])
            store.set_setting(w, 'default_profile', 'p')
            request = AnalysisRequest(mode='ai', additional_ai_review=True)
            last = [0.]
            def progress(stage, completed, total):
                if time.monotonic() - last[0] >= 10:
                    print(json.dumps({'stage': stage, 'completed': completed, 'total': total}), flush=True)
                    last[0] = time.monotonic()
            preview = preview_analysis(store, w, request, progress=progress)
            assert preview['valid'], preview['blocked'][:5]
            report = {'files': preview['files'], 'planned_tasks': preview['units'],
                'source_context_views': preview['source_context_pages'], 'projection_tasks': preview['semantic_pages'],
                'maximum_disclosed_characters': max(a['source_characters'] for a in preview['allowances']),
                'maximum_request_characters': max(a['required_characters'] for a in preview['allowances']),
                'model_context_tokens': input_tokens, 'live_provider_calls': 0,
                'qualification': 'Request fitting, stored checkpoints and publication only; no model precision claim.'}
            print(json.dumps({'preview': report}), flush=True)
            seen = set()
            calls = 0
            def provider(http_request):
                nonlocal calls
                body = json.loads(http_request.content)
                system, user = (m['content'] for m in body['messages'])
                active = profile.model_copy(update={'max_tokens': body['max_tokens']})
                assert request_allowance(active, system, user, privacy_chars=8000).valid
                context = json.loads(user[user.index('{'):])
                items = context.get('items', [context])
                results = []
                for item in items:
                    uid = item['unit']['unit_id']
                    assert uid not in seen
                    seen.add(uid)
                    results.append({'unit_id': uid, 'coverage': {'status': 'partial'}})
                payload = {'items': results} if 'items' in context else results[0]
                calls += 1
                if calls % 500 == 0:
                    print(json.dumps({'mock_requests': calls, 'unique_checkpointed_inputs': len(seen)}), flush=True)
                return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(payload)}, 'finish_reason': 'stop'}]})
            if execute:
                result = run_analysis(store, w, request, transport=httpx.MockTransport(provider))
                assert result.status == 'committed', result.reasons
                assert len(seen) == preview['units']
                report.update(mock_requests=calls, unique_inputs=len(seen), status=result.status,
                              publications=len(store.runs(w)))
            report['seconds'] = round(time.monotonic() - started, 3)
            return report
        finally:
            store.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--input-tokens', type=int, default=16384)
    parser.add_argument('--fixture-home', type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate(execute=args.execute, input_tokens=args.input_tokens, fixture_home=args.fixture_home), indent=2))
