from test_ai_file_parts import source
from test_ai_linking_review import op
from test_ai_token_budget import model

from dataforge.ai_analysis_models import (
    PartExtraction,
    ResourceReference,
    SourceReference,
)
from dataforge.ai_composition import plan_file_consolidation
from dataforge.ai_context import plan_file_parts


def consolidation_fixture():
    snapshot = source('x' * 16000)
    profile = model(70000).model_copy(update={'max_tokens': 4000})
    parts = plan_file_parts(snapshot, {}, profile)
    records = []
    for i, part in enumerate(parts):
        operations = []
        for j in range(12):
            operation = op(f'operation{j}', writes=[f't{j}'])
            operation.evidence = [SourceReference(file_id=part.file_id, content_hash=part.content_hash,
                start_offset=part.start_offset, end_offset=part.end_offset)]
            operations.append(operation)
        records.append((part, PartExtraction(part_id=part.part_id, operations=operations)))
    context = {'sources': {snapshot.file_id: snapshot}, 'settings': {'case_sensitive': True}}
    return records, profile, context


def test_connected_oversized_component_is_not_split_or_truncated():
    records, profile, context = consolidation_fixture()
    for _, result in records:
        for j, operation in enumerate(result.operations):
            if j:
                operation.reads = [ResourceReference(name=f't{j-1}')]
    work = plan_file_consolidation(records, profile, context=context)
    assert len(work) == 1 and work[0].overflow
    assert len(work[0].inputs['operations']) == sum(len(r.operations) for _, r in records)
    assert set(work[0].inputs['part_ids']) == {p.part_id for p, _ in records}
