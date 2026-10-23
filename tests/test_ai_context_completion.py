from dataforge.ai_analysis_models import MissingContext, PartExtraction
from dataforge.ai_context import SourceSnapshot, plan_file_parts
from dataforge.ai_context_index import build_context_index, plan_context_completion
from test_ai_context_index import prepared
from test_ai_token_budget import model


def test_one_completion_only_when_new_relevant_context_is_available():
    consumer = SourceSnapshot('c', 'hc', 'c.sas', '.sas', 'job', '%load;', 'sas')
    definition = SourceSnapshot('d', 'hd', 'd.sas', '.sas', 'job', '%macro load; data b; set a; run; %mend;', 'sas')
    part = plan_file_parts(consumer, {}, model())[0]
    index = build_context_index(prepared(consumer, definition), [])
    item = PartExtraction(part_id=part.part_id, missing_context=[MissingContext(symbol='load', kind='macro', scope='job')])
    works = plan_context_completion([(part, item)], index)
    assert len(works) == 1
    assert works[0].original_part_id == part.part_id
    assert works[0].catalog_revision == index.revision
    assert not plan_context_completion([(part, item)], index, completed={part.part_id})
    item.missing_context[0].consumed_fingerprint = works[0].context.fingerprint
    assert not plan_context_completion([(part, item)], index)
    assert not plan_context_completion([(part, item)], build_context_index(prepared(consumer), []))
