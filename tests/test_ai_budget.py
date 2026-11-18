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
