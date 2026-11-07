import json
from dataclasses import replace

from test_ai_file_parts import source
from test_ai_token_budget import model

from dataforge.ai_batching import pack_request
from dataforge.ai_context import plan_file_parts
from dataforge.ai_wire import decode_extractions


def test_token_fit_supports_more_than_eight_files_and_preserves_partial_siblings():
    profile = model(200000).model_copy(update={'max_tokens': 32000})
    sources = [replace(source('select 1;'), file_id=str(i)) for i in range(12)]
    parts = [part for item in sources for part in plan_file_parts(item, {}, profile)]
    request = pack_request(parts, profile, {'sources': {s.file_id: s for s in sources}})
    assert len(request.part_ids) == 12 and request.budget.fits
    assert request.system.count('Item schema:') == 1
    assert len(json.loads(request.user)['items']) == 12
    good, errors = decode_extractions({'items': [{'part_id': parts[0].part_id}]}, parts)
    assert set(good) == {parts[0].part_id}
    assert len(errors) == 11
