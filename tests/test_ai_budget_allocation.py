import json

import httpx
import pytest
from test_ai_resumable_files import configured, empty_provider
from test_ai_token_budget import model

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_budget import allocate_analysis_profile, profile_recommendations, request_budget
from dataforge.analysis_service import preview_analysis, run_analysis
from dataforge.ingestion import Importer
from dataforge.store import Store


def automatic(context=70000, **caps):
    return model(context, **caps).model_copy(update={'output_mode': 'automatic'})


@pytest.mark.parametrize('capacity,share,output,input_', [(70000, 30, 19950, 46550),
    (200000, 30, 57000, 133000), (1000000, 30, 285000, 665000),
    (70000, 10, 6650, 59850), (70000, 50, 33250, 33250),
    (200000, 10, 19000, 171000), (200000, 50, 95000, 95000),
    (1000000, 10, 95000, 855000), (1000000, 50, 475000, 475000)])
def test_share_allocates_usable_shared_capacity_without_eight_k_cap(capacity, share, output, input_):
    effective, allocation = allocate_analysis_profile(automatic(capacity), AnalysisRequest(mode='ai', output_share=share))
    assert effective.max_tokens == allocation['output_allowance'] == output
    assert allocation['input_allowance'] == input_
    assert request_budget(effective, '{}', output).input_limit == input_
    assert profile_recommendations(effective.model_capabilities)['max_tokens'] == int(capacity * .95 * .3)


def test_model_clamps_and_safety_reasoning_are_accounted_once():
    p = automatic(output_tokens=8192, input_tokens=20000, reasoning_tokens=2000, reasoning_accounting='shared_context')
    effective, a = allocate_analysis_profile(p, AnalysisRequest(mode='ai'))
    assert a['output_allowance'] == 8192 and a['input_allowance'] == 20000
    assert a['safety_reserve'] == 3500 and a['reasoning_reserve'] == 2000
    assert 'model_output_limit' in a['clamps'] and 'model_input_limit' in a['clamps']
    body = json.dumps({'system': 'instructions', 'schema': 'x' * 1000, 'definitions': 'x' * 1000, 'source': 'x' * 1000})
    b = request_budget(effective, body, effective.max_tokens)
    assert b.input_count == len(body.encode()) + 256 and b.input_limit == 20000
    included, a2 = allocate_analysis_profile(automatic(reasoning_tokens=2000), AnalysisRequest(mode='ai'))
    assert a2['reasoning_reserve'] == 0 and included.max_tokens == 19950


def test_separate_windows_use_output_capacity_preference_without_combined_constraint():
    effective, a = allocate_analysis_profile(automatic(200000, input_tokens=200000, output_tokens=32000, window='separate'),
        AnalysisRequest(mode='ai'))
    assert a['input_allowance'] == 190000 and a['output_allowance'] == 9600
    assert request_budget(effective, '{}', 9600).input_limit == 190000
    assert a['window'] == 'separate'


def test_explicit_run_overrides_then_custom_profile_then_slider_precedence():
    p = model()
    effective, a = allocate_analysis_profile(p, AnalysisRequest(mode='ai', output_share=50))
    assert effective.max_tokens == 8000 and 'saved_custom_output_limit' in a['clamps']
    effective, a = allocate_analysis_profile(p, AnalysisRequest(mode='ai', output_share=10,
        output_token_limit=15000, input_token_limit=12000))
    assert effective.max_tokens == 15000 and a['input_allowance'] == 12000
    assert p.max_tokens == 8000  # Never mutate the saved profile.
    effective, a = allocate_analysis_profile(automatic(output_tokens=10000), AnalysisRequest(mode='ai', output_token_limit=50000))
    assert effective.max_tokens == 10000 and 'model_output_limit' in a['clamps']


def test_dynamic_catalog_capacity_requires_existing_manual_confirmation():
    p = automatic(dynamic=True)
    p.model_capabilities = p.model_capabilities.model_copy(update={'source': 'catalog'})
    with pytest.raises(ValueError, match='route_safe_capacity'):
        allocate_analysis_profile(p, AnalysisRequest(mode='ai'))
    p.model_capabilities = p.model_capabilities.model_copy(update={'source': 'manual'})
    _, a = allocate_analysis_profile(p, AnalysisRequest(mode='ai'))
    assert a['source'] == 'manual' and a['dynamic']


def test_preview_execution_pins_allocation_and_requests_have_no_history(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('allocation wire')
    configured(store, w, automatic())
    Importer(store, w).files([(f'{i}.sql', b'select 1;' + b' ' * 9000) for i in range(10)], {'.sql'})
    request = AnalysisRequest(mode='ai', output_share=30)
    preview = preview_analysis(store, w, request)
    assert preview['valid'] and preview['allocation']['output_allowance'] == 19950
    calls, seen = [], []
    good = empty_provider(seen)
    def provider(r):
        body = json.loads(r.content)
        calls.append(body)
        assert body['max_tokens'] == preview['allocation']['output_allowance']
        assert [m['role'] for m in body['messages']] == ['system', 'user']
        assert not {'previous_response_id', 'conversation', 'conversation_id'} & body.keys()
        assert request_budget(allocate_analysis_profile(automatic(), request)[0],
                              json.dumps(body, ensure_ascii=False, separators=(',', ':')), body['max_tokens']).fits
        return good(r)
    report = run_analysis(store, w, request, transport=httpx.MockTransport(provider))
    assert report.status == 'committed'
    assert len(calls) > 1 and any(len(json.loads(b['messages'][1]['content'])['items']) > 1 for b in calls)
    parts = [i['part']['part_id'] for b in calls for i in json.loads(b['messages'][1]['content'])['items']]
    assert len(parts) == len(set(parts)) == 10
    summary = json.loads(store.rows('SELECT summary FROM ai_analysis_runs')[0]['summary'])
    assert summary['allocation'] == preview['allocation']
    for packing in preview['packing']:
        assert packing['files'] and packing['parts'] and packing['stop_reasons']
        assert packing['estimated_input_tokens'] <= packing['input_allowance']
    store.close()


def test_analysis_ui_slider_and_optional_advanced_use_same_allocation(tmp_path, monkeypatch):
    from pathlib import Path

    import streamlit as st
    from streamlit.testing.v1 import AppTest

    from ui.common import get_store
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    store = get_store(str(tmp_path))
    w = store.create_workspace('budget UI')
    configured(store, w, automatic(output_tokens=32000))
    Importer(store, w).files([('q.sql', b'select 1;')], {'.sql'})
    monkeypatch.setattr('dataforge.llm.Adapter.complete', lambda *a, **k: pytest.fail('UI made a provider call'))
    view = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    view.switch_page('ui/pages/analysis.py').run()
    next(c for c in view.checkbox if c.label == 'Use AI for analysis').check().run()
    slider = next(s for s in view.slider if s.label == 'Maximum output share (%)')
    assert slider.value == 30 and slider.min == 10 and slider.max == 50
    assert any('19,950' in m.value for m in view.metric)
    slider.set_value(50).run()
    assert not view.exception
    assert any('32,000' in m.value for m in view.metric)
    assert any('model output' in c.value.lower() for c in view.caption)
    next(c for c in view.checkbox if c.label == 'Override per-request token allowances').check().run()
    next(n for n in view.number_input if n.label == 'Maximum output tokens per request (optional)').set_value(15000).run()
    assert not view.exception and any('15,000' in m.value for m in view.metric)
    assert json.loads(store.rows('SELECT config FROM llm_profiles')[0]['config'])['max_tokens'] == 8000
    st.cache_resource.clear()


@pytest.mark.parametrize('model_output,expected', [(None, 18483), (8192, 8192)])
def test_explicit_slider_change_overrides_saved_default_but_respects_model_cap(tmp_path, monkeypatch, model_output, expected):
    from pathlib import Path

    import streamlit as st
    from streamlit.testing.v1 import AppTest

    from ui.common import get_store
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    store = get_store(str(tmp_path))
    w = store.create_workspace('Custom slider')
    p = model(38912, output_tokens=model_output).model_copy(update={'max_tokens': 8192})
    configured(store, w, p)
    Importer(store, w).files([('q.sql', b'select 1;')], {'.sql'})
    view = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    view.switch_page('ui/pages/analysis.py').run()
    next(c for c in view.checkbox if c.label == 'Use AI for analysis').check().run()
    next(s for s in view.slider if s.label == 'Maximum output share (%)').set_value(50).run()
    assert not view.exception
    metrics = {m.label: m.value for m in view.metric}
    assert metrics['Maximum output allowance per request (tokens)'] == f'{expected:,}'
    assert metrics['Effective input allowance (tokens)'] == f'{36966 - expected:,}'
    if model_output:
        assert any('will stay fixed' in c.value for c in view.caption)
    assert json.loads(store.rows('SELECT config FROM llm_profiles')[0]['config'])['max_tokens'] == 8192
    st.cache_resource.clear()


def test_run_allocation_keeps_profile_bound_session_credentials(tmp_path, monkeypatch):
    from dataforge.agent.service import AgentService
    from dataforge.connections import RuntimeConnections
    from dataforge.model_capabilities import bind_capabilities, runtime_profile
    from dataforge.project_analysis import _BoundConnections
    p = automatic().model_copy(update={'key_env': 'DATAFORGE_ALLOCATION_TEST_KEY'})
    p.model_capabilities = bind_capabilities(p.model_capabilities, p)
    monkeypatch.delenv(p.key_env, raising=False)
    store = Store(tmp_path)
    w = store.create_workspace('bound budget')
    configured(store, w, p)
    Importer(store, w).files([('q.sql', b'select 1;')], {'.sql'})
    service = AgentService(store)
    manager = RuntimeConnections()
    manager.register('DATAFORGE_RUNTIME_CREDENTIAL', 'synthetic-allocation-secret')
    service.runtime_connections[w, 'p'] = manager
    service.runtime_profiles[w, 'p'] = runtime_profile(p)
    good = empty_provider([])
    def provider(request):
        assert request.headers['Authorization'] == 'Bearer synthetic-allocation-secret'
        return good(request)
    report = run_analysis(store, w, AnalysisRequest(mode='ai'), connections=_BoundConnections(service, w),
                          transport=httpx.MockTransport(provider))
    assert report.status == 'committed', report.reasons
    assert manager.registered('DATAFORGE_RUNTIME_CREDENTIAL')
    assert 'synthetic-allocation-secret' not in json.dumps(store.rows('SELECT summary FROM ai_analysis_runs'))
    service.close()
    store.close()


def test_saved_allocation_is_pinned_on_resume_and_legacy_checkpoint_keeps_budget(tmp_path, monkeypatch):
    import dataforge.analysis_service as service
    from dataforge.llm import Profile
    from dataforge.model_capabilities import execution_profile
    store = Store(tmp_path)
    w = store.create_workspace('budget resume')
    p = model()
    configured(store, w, p)
    Importer(store, w).files([('q.sql', b'select 1;')], {'.sql'})
    planner = service.plan_file_consolidation
    def stopped(*args, **kwargs):
        raise ValueError('synthetic_before_publication')
    monkeypatch.setattr(service, 'plan_file_consolidation', stopped)
    first = run_analysis(store, w, AnalysisRequest(mode='ai', output_share=40), transport=httpx.MockTransport(empty_provider([])))
    assert first.status == 'failed'
    changed = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id, output_share=50))
    assert changed.status == 'blocked' and changed.reasons == ['Continuation token allocation is pinned']
    summary = json.loads(store.rows('SELECT summary FROM ai_analysis_runs WHERE run_id=?', [first.run_id])[0]['summary'])
    for key in ('budget_policy', 'output_share', 'input_token_limit', 'output_token_limit'):
        summary['request'].pop(key, None)
    summary['pin']['profile'] = service._hash(execution_profile(Profile.model_validate_json(p.model_dump_json())))
    summary.pop('allocation', None)
    store.execute('UPDATE ai_analysis_runs SET summary=? WHERE run_id=?', [json.dumps(summary), first.run_id])
    store.close()
    store = Store(tmp_path)
    monkeypatch.setattr(service, 'plan_file_consolidation', planner)
    resumed = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id),
        transport=httpx.MockTransport(lambda r: pytest.fail('Saved extraction was resent')))
    assert resumed.status == 'committed', resumed.reasons
    final = json.loads(store.rows('SELECT summary FROM ai_analysis_runs WHERE run_id=?', [first.run_id])[0]['summary'])
    assert final['allocation']['policy'] == 'legacy' and final['allocation']['output_allowance'] == 8000
    store.close()


def test_missing_optional_limits_are_explicit_and_unknown_shared_window_is_not_invented():
    p = automatic()
    effective, a = allocate_analysis_profile(p, AnalysisRequest(mode='ai'))
    assert a['output_capacity'] is None and a['notes'] and effective.max_tokens == 19950
    p = automatic(None, input_tokens=70000, output_tokens=32000, window='separate')
    effective, a = allocate_analysis_profile(p, AnalysisRequest(mode='ai'))
    assert a['input_allowance'] == 66500 and effective.max_tokens == 9600
    p = automatic(None, input_tokens=70000, output_tokens=32000)
    with pytest.raises(ValueError, match='shared_model_context_capacity_required'):
        allocate_analysis_profile(p, AnalysisRequest(mode='ai'))


@pytest.mark.parametrize('provider', ['OpenAI', 'OmniRoute', 'Anthropic', 'Ollama', 'Gemini'])
def test_provider_wire_is_independent_and_preserves_maximum_output_parameter(provider):
    from dataforge.llm import Adapter
    from dataforge.model_capabilities import bind_capabilities
    p = automatic().model_copy(update={'provider': provider})
    p.model_capabilities = bind_capabilities(p.model_capabilities, p)
    p, _ = allocate_analysis_profile(p, AnalysisRequest(mode='ai'))
    _, first = Adapter.completion_request(p, 'stable instructions and schema', 'current source batch A')
    _, second = Adapter.completion_request(p, 'stable instructions and schema', 'current source batch B')
    assert 'current source batch A' not in json.dumps(second)
    assert not {'previous_response_id', 'conversation_id', 'conversation'} & second.keys()
    if provider == 'Anthropic':
        assert second['messages'] == [{'role': 'user', 'content': 'current source batch B'}]
        assert second['system'] == first['system'] and second['max_tokens'] == 19950
    elif provider == 'Gemini':
        assert len(second['contents']) == 1 and second['generationConfig']['maxOutputTokens'] == 19950
    else:
        assert [m['role'] for m in second['messages']] == ['system', 'user']
        output = second['options']['num_predict'] if provider == 'Ollama' else second['max_completion_tokens' if provider == 'OpenAI' else 'max_tokens']
        assert output == 19950


def test_existing_cli_and_mcp_accept_optional_run_allocation_fields(tmp_path):
    import asyncio

    from typer.main import get_command

    from dataforge.agent.mcp_server import create_server
    from dataforge.agent.service import AgentService
    from dataforge.cli import app
    command = get_command(app).commands['lineage'].commands['build']
    flags = {flag for p in command.params for flag in [*p.opts, *p.secondary_opts]}
    assert {'--output-share', '--input-token-limit', '--output-token-limit'} <= flags
    store = Store(tmp_path)
    service = AgentService(store)
    server = create_server(service)
    definitions = asyncio.run(server.list_tools())
    for name in ('start_lineage_analysis', 'preview_project_analysis'):
        fields = next(t for t in definitions if t.name == name).inputSchema['properties']
        assert {'output_share', 'input_token_limit', 'output_token_limit'} <= fields.keys()
    service.close()
    store.close()
