import json

import pytest
from test_ai_token_budget import model

from dataforge.ai_analysis_models import PartExtraction
from dataforge.ai_batching import pack_request
from dataforge.ai_context import SourceSnapshot, plan_file_parts
from dataforge.ai_wire import decode_extractions


def source(code, extension='.sql'):
    return SourceSnapshot('file', 'hash', 'query' + extension, extension, 'job', code, extension[1:])


@pytest.mark.parametrize('code', ['select 1;\r\n-- tail 界', 'select ' + ', '.join(f'c{i}' for i in range(400)),
                                'data out; set raw; ' + 'x=x+1; ' * 2000 + 'run;'])
def test_file_plan_accounts_for_every_character_once(code):
    profile = model()
    parts = plan_file_parts(source(code), {}, profile)
    assert parts[0].start_offset == 0
    assert parts[-1].end_offset == len(code)
    assert all(a.end_offset == b.start_offset for a, b in zip(parts, parts[1:]))
    request = pack_request(parts, profile, {'sources': {'file': source(code)}})
    assert request.budget.fits
    assert json.loads(request.serialized_payload) == request.payload


def test_large_context_is_usable_and_small_files_share_envelope():
    profile = model(200000).model_copy(update={'max_tokens': 32000})
    a = source('-- comment\n' + ' ' * 12000 + 'select 1;')
    b = source('select 2;')
    b = type(b)(**{**b.__dict__, 'file_id': 'other'})
    parts = [*plan_file_parts(a, {}, profile), *plan_file_parts(b, {}, profile)]
    assert len(parts) == 2
    request = pack_request(parts, profile, {'sources': {'file': a, 'other': b}})
    assert len(request.part_ids) == 2
    assert request.budget.fits


def test_response_membership_and_partial_siblings():
    parts = plan_file_parts(source('select 1;'), {}, model())
    pid = parts[0].part_id
    good, errors = decode_extractions({'items': [{'part_id': pid}, {'part_id': 'unknown'}]}, parts)
    assert isinstance(good[pid], PartExtraction)
    assert errors['unknown'] == 'unknown_response_part'
    good, errors = decode_extractions({'items': [{'part_id': pid}, {'part_id': pid}]}, parts)
    assert not good and errors[pid] == 'duplicate_response_part'
    with pytest.raises(ValueError):
        decode_extractions('{"items":[', parts)
