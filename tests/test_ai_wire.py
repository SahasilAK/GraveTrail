import json

import pytest


def test_truncation_decoder_recovers_only_unambiguous_complete_items():
    from types import SimpleNamespace

    from dataforge.ai_wire import decode_extractions
    parts = [SimpleNamespace(part_id=p) for p in ('a', 'b', 'c')]
    a = {'part_id': 'a', 'coverage': 'complete', 'unresolved': ['nested { \\" string }']}
    prefix = '{"items":[' + json.dumps(a) + ','
    diagnostics = {}
    valid, errors = decode_extractions(prefix + '{"part_id":"b","coverage":"com', parts,
        allow_truncated=True, diagnostics=diagnostics)
    assert set(valid) == {'a'} and set(errors) == {'b', 'c'}
    assert diagnostics['__truncation__']['code'] == 'truncated_extraction_response'
    for tail in ('{"part_id":"a","coverage":"com', '{"coverage":"com', '{"part_id":"unknown",',
                 '{"part_id":"b","part_id":"a","coverage":'):
        with pytest.raises(ValueError):
            decode_extractions(prefix + tail, parts, allow_truncated=True)
    with pytest.raises(ValueError):
        decode_extractions(prefix + '{"part_id":"b",', parts)
    for bad in ('{"items":[],"items":[]}', '{"items":[{"part_id":"a","part_id":"b"}]}'):
        with pytest.raises(ValueError):
            decode_extractions(bad, parts, allow_truncated=True)
