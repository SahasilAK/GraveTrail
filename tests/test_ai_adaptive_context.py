"""Lossless file ranges and output pressure replace source/context products."""
from dataclasses import replace

import pytest
from test_ai_file_parts import source
from test_ai_token_budget import model

from dataforge.ai_analysis_models import OperationRecord, PartExtraction, SourceReference
from dataforge.ai_batching import pack_request
from dataforge.ai_context import plan_file_parts
from dataforge.ai_validation import validate_extraction


@pytest.mark.parametrize('family', ['sql', 'sas', 'dbt'])
def test_oversized_indivisible_sources_have_exact_coverage(family):
    text = source(('select id from a union all ' * 500 if family != 'sas' else
                   '%macro load; data out; set a; ' + 'id=id+1;' * 1500 + 'run; %mend;'))
    text = replace(text, source_kind=family, extension='.sas' if family == 'sas' else '.sql')
    profile = model().model_copy(update={'max_tokens': 2048})
    parts = plan_file_parts(text, {}, profile)
    assert len(parts) > 1
    assert ''.join(text.code[p.start_offset:p.end_offset] for p in parts) == text.code
    for part in parts:
        assert pack_request([part], profile, {'sources': {text.file_id: text}}).budget.fits


def test_more_than_one_hundred_inputs_and_repeated_roles_are_not_clipped():
    text = source('select ' + ','.join(f'c{i}' for i in range(150)) + ' from a;')
    part = plan_file_parts(text, {}, model())[0]
    ref = SourceReference(file_id=text.file_id, content_hash=text.content_hash, start_offset=0, end_offset=len(text.code))
    dependencies = [{'table': 'a', 'column': f'c{i}', 'role': role} for i in range(150)
                    for role in ('value', 'row_filter', 'order')]
    operation = OperationRecord(operation_id='wide', kind='CREATE', evidence=[ref], derivations=[
        {'fact_id': 'wide', 'target_table': 'b', 'target_column': 'x', 'inputs': dependencies, 'evidence': [ref]}])
    result = validate_extraction(PartExtraction(part_id=part.part_id, operations=[operation]), part, {text.file_id: text})
    assert len(result.operations[0].derivations[0].inputs) == 450
    assert result.operations[0].derivations[0].inputs[-1].role == 'order'


def test_fixed_protocol_error_stops_before_source_subdivision():
    text = source('x' * 100000)
    with pytest.raises(ValueError, match='input_budget'):
        plan_file_parts(text, {}, model(1000))


def test_exact_evidence_does_not_allow_a_hidden_source_range():
    text = source('select id from a; select secret from denied;')
    part = plan_file_parts(text, {}, model())[0].model_copy(update={'end_offset': 17})
    reference = SourceReference(file_id=text.file_id, content_hash=text.content_hash, start_offset=18, end_offset=len(text.code))
    item = PartExtraction(part_id=part.part_id, operations=[OperationRecord(operation_id='forged', kind='READ', evidence=[reference])])
    with pytest.raises(ValueError, match='source_reference'):
        validate_extraction(item, part, {text.file_id: text})
