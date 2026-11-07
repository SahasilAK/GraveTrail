import pytest
from test_ai_file_parts import source
from test_ai_token_budget import model

from dataforge.ai_analysis_models import OperationRecord, PartExtraction, ResourceReference, SourceReference
from dataforge.ai_context import plan_file_parts
from dataforge.ai_validation import validate_extraction


def test_valid_source_backed_inference_does_not_invoke_static_semantics(monkeypatch):
    text = source('vendor transform strange syntax raw.a into mart.b;')
    part = plan_file_parts(text, {}, model())[0]
    reference = SourceReference(file_id=text.file_id, content_hash=text.content_hash,
                                start_offset=0, end_offset=len(text.code))
    item = PartExtraction(part_id=part.part_id, operations=[OperationRecord(operation_id='local',
        kind='VENDOR_TRANSFORM', evidence=[reference], reads=[ResourceReference(name='raw.a')],
        writes=[ResourceReference(name='mart.b')])])
    monkeypatch.setattr('dataforge.parsers.sql.parse_sql', lambda *a, **k: pytest.fail('Static approval invoked'))
    validated = validate_extraction(item, part, {text.file_id: text})
    assert len(validated.operations) == 1
    assert validated.operations[0].status == 'inferred'
    assert validated.operations[0].operation_id != 'local'


@pytest.mark.parametrize('change', [{'content_hash': 'forged'}, {'file_id': 'denied'}, {'end_offset': 999}])
def test_forged_evidence_is_rejected(change):
    text = source('select id from a;')
    part = plan_file_parts(text, {}, model())[0]
    ref = {'file_id': text.file_id, 'content_hash': text.content_hash, 'start_offset': 0, 'end_offset': len(text.code), **change}
    item = PartExtraction(part_id=part.part_id, operations=[OperationRecord(operation_id='x', kind='READ', evidence=[ref])])
    with pytest.raises(ValueError, match='source_reference'):
        validate_extraction(item, part, {text.file_id: text})
