import json

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_context import AIExecutionContext, plan_ai_units
from dataforge.llm import Profile
from tests.test_ai_analysis_context import prepared


def test_batch_full_envelope_and_partial_response_identity():
    from dataforge.ai_batching import batch_prompt, decode_batch_response, pack_batch
    units = plan_ai_units(prepared('select 1; select 2; select 3;')).units
    execution = AIExecutionContext(AnalysisRequest(mode='ai', max_files_per_request=1))
    p = Profile(provider='Ollama', base_url='http://localhost:11434', model='m', max_tokens=32000, context_chars=100000)
    batch = pack_batch(units, {u.unit_id: [] for u in units}, execution, p, width=8, privacy_chars=100000)
    assert len(batch) == 3
    system, user = batch_prompt(batch, execution, {u.unit_id: [] for u in units})
    assert all(u.unit_id in user for u in units)
    assert 'schema' in user and len(system) > 100
    raw = json.dumps({'items': [{'unit_id': units[0].unit_id, 'coverage': {'status': 'partial'}}]})
    good, errors = decode_batch_response(raw, batch)
    assert set(good) == {units[0].unit_id}
    assert set(errors) == {u.unit_id for u in units[1:]}
    raw = json.dumps({'items': [{'unit_id': units[0].unit_id}, {'unit_id': units[0].unit_id}]})
    good, errors = decode_batch_response(raw, batch)
    assert not good and units[0].unit_id in errors


def test_auto_growth_and_size_failure():
    from dataforge.ai_batching import next_batch_width
    assert next_batch_width(1, clean_streak=2, outcome='clean') == 1
    assert next_batch_width(1, clean_streak=3, outcome='clean') == 2
    assert next_batch_width(8, clean_streak=9, outcome='size_failure') == 4
