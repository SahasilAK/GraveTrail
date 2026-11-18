import pytest
from test_ai_file_parts import source
from test_ai_token_budget import model

from dataforge.ai_analysis_models import OperationRecord, PartExtraction
from dataforge.ai_context import plan_file_parts
from dataforge.ai_validation import validate_extraction


@pytest.mark.parametrize('change', [{'content_hash': 'forged'}, {'file_id': 'denied'}, {'end_offset': 999}])
def test_forged_evidence_is_rejected(change):
    text = source('select id from a;')
    part = plan_file_parts(text, {}, model())[0]
    ref = {'file_id': text.file_id, 'content_hash': text.content_hash, 'start_offset': 0, 'end_offset': len(text.code), **change}
    item = PartExtraction(part_id=part.part_id, operations=[OperationRecord(operation_id='x', kind='READ', evidence=[ref])])
    with pytest.raises(ValueError, match='source_reference'):
        validate_extraction(item, part, {text.file_id: text})
