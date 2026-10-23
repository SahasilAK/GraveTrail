from test_ai_file_parts import source
from test_ai_token_budget import model

from dataforge.ai_analysis_models import OperationRecord, PartExtraction, ResourceReference, SourceReference
from dataforge.ai_composition import assemble_file_extraction, plan_file_consolidation
from dataforge.ai_context import plan_file_parts


def test_consolidation_is_bounded_and_original_details_survive_overflow():
    profile = model().model_copy(update={'max_tokens': 2048})
    snapshot = source('select ' + 'id, ' * 2000 + 'id from a;')
    parts = plan_file_parts(snapshot, {}, profile)
    assert len(parts) > 1
    records = []
    for i, part in enumerate(parts):
        ref = SourceReference(**part.model_dump(include={'file_id', 'content_hash', 'start_offset', 'end_offset'}))
        operation = OperationRecord(operation_id=f'op{i}', kind='READ', evidence=[ref],
                                    reads=[ResourceReference(name='a')], limitations=['x' * 20000])
        records.append((part, PartExtraction(part_id=part.part_id, operations=[operation])))
    work = plan_file_consolidation(records, profile)
    assert work and all(w.overflow for w in work)
    file = assemble_file_extraction(snapshot, records, [], provenance={})
    assert len(file.operations) == len(records)
    assert file.semantic_coverage == 'partial'


def test_saved_part_and_file_records_survive_reopening(tmp_path):
    from dataforge.ai_analysis_store import (
        load_file_extractions,
        load_file_parts,
        save_file_extraction,
        save_part_extraction,
        save_run,
    )
    from dataforge.store import Store
    store = Store(tmp_path)
    workspace = store.create_workspace('save')
    save_run(store, workspace, 'run', mode='ai')
    snapshot = source('select 1;')
    part = plan_file_parts(snapshot, {}, model())[0]
    extraction = PartExtraction(part_id=part.part_id, coverage='no_operations')
    save_part_extraction(store, workspace, 'run', part, extraction)
    final = assemble_file_extraction(snapshot, [(part, extraction)], [], provenance={'model': 'm'})
    save_file_extraction(store, workspace, 'run', final)
    store.close()
    store = Store(tmp_path)
    assert load_file_parts(store, workspace, 'run') == [(part, extraction)]
    assert load_file_extractions(store, workspace, 'run') == [final]
    store.close()
