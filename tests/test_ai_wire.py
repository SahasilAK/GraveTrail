import json

import pytest

from dataforge.ai_analysis_models import AnalysisUnit, EvidenceCitation
from dataforge.ai_wire import decode_project_result, encode_project_result, wire_schema


def unit():
    code = 'select 1;' + ' ' * 50000
    return AnalysisUnit(unit_id='u', file_id='f', content_hash='h', path='a.sql', extension='.sql',
                        first=1, last=1, start_offset=0, end_offset=len(code), code=code)


def test_compact_references_expand_only_against_exact_host_unit():
    u = unit()
    payload = {'unit_id': 'u', 'relationships': [{'source': 'a', 'target': 'b', 'operation': 'CREATE',
               'evidence': {'unit_id': 'u'}}], 'coverage': {'status': 'complete'}}
    response = decode_project_result('project_lineage', payload, u)
    assert response.relationships[0].evidence == EvidenceCitation.from_unit(u)
    packed = encode_project_result(response)
    assert len(json.dumps(packed)) < 1000
    assert decode_project_result('project_lineage', packed, u) == response
    for evidence in ({'unit_id': 'other'}, {'unit_id': 'u', 'quote': 'select'}, {}):
        payload['relationships'][0]['evidence'] = evidence
        with pytest.raises(ValueError):
            decode_project_result('project_lineage', payload, u)


def test_review_reference_schema_and_candidate_validation():
    result = decode_project_result('lineage_review', {'decisions': [{'candidate_id': 'c',
        'decision': 'supported', 'evidence': [{'unit_id': 'u'}]}]}, unit())
    result.assert_candidates({'c'})
    assert 'quote' not in json.dumps(wire_schema('lineage_review'))
    with pytest.raises(ValueError):
        decode_project_result('lineage_review', {'decisions': [{'candidate_id': 'c',
            'decision': 'supported', 'evidence': []}]}, unit())


def test_generated_wire_schema_assets_match_runtime_contracts():
    from dataforge.llm import PROJECT_TASKS, PROMPTS
    for task in PROJECT_TASKS:
        assert json.loads((PROMPTS / 'schemas' / f'{task}_wire_response.json').read_text(encoding='utf-8')) == wire_schema(task)


def test_many_claims_store_compactly_even_when_canonical_expansion_exceeds_record_limit():
    u = unit()
    payload = {'unit_id': 'u', 'relationships': [{'source': 'a', 'target': 'b', 'operation': 'CREATE',
               'evidence': {'unit_id': 'u'}}] * 100,
               'columns': [{'table': 'a', 'column': 'x', 'context': 'SELECT', 'evidence': {'unit_id': 'u'}}] * 100,
               'assets': [{'name': 'a', 'role': 'read', 'evidence': {'unit_id': 'u'}}] * 100,
               'derivations': [{'target_table': 'b', 'target_column': 'x', 'expression': '1',
                  'category': 'constant', 'evidence': {'unit_id': 'u'}}] * 100}
    response = decode_project_result('project_lineage', payload, u)
    assert len(response.model_dump_json()) > 16 * 1024 * 1024
    assert len(json.dumps(encode_project_result(response))) < 100000


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


@pytest.mark.parametrize('suffix', ['}', '],"extra":1}', '],"items":[]}', ']garbage'])
def test_truncation_decoder_rejects_malformed_envelopes(suffix):
    from types import SimpleNamespace

    from dataforge.ai_wire import decode_extractions
    with pytest.raises(ValueError):
        decode_extractions('{"items":[{"part_id":"a","coverage":"no_operations"}' + suffix,
            [SimpleNamespace(part_id='a')], allow_truncated=True)


def test_truncation_after_items_array_preserves_complete_items():
    from types import SimpleNamespace

    from dataforge.ai_wire import decode_extractions
    valid, errors = decode_extractions('{"items":[{"part_id":"a","coverage":"no_operations"}]',
        [SimpleNamespace(part_id='a')], allow_truncated=True)
    assert set(valid) == {'a'} and not errors
