import json

from test_ai_token_budget import model

from dataforge.ai_budget import request_budget
from dataforge.llm import Adapter


def test_actual_provider_body_including_framing_is_the_budgeted_object():
    profile = model()
    _, body = Adapter.completion_request(profile, 'instructions and schema', '{"items":[]}')
    serialized = json.dumps(body, ensure_ascii=False, separators=(',', ':'))
    budget = request_budget(profile, serialized, 8000)
    assert budget.fits
    assert budget.input_count == len(serialized.encode()) + 256
    assert budget.input_count > len(body['messages'][-1]['content'])


def test_model_output_limit_cannot_be_bypassed_by_large_input_window():
    profile = model(1000000, output_tokens=1000)
    budget = request_budget(profile, '{}', 8000)
    assert not budget.fits
    assert budget.reasons == ('reserved_output_exceeds_model_limit',)
