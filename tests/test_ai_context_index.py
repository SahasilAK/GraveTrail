import json

from test_ai_token_budget import model

from dataforge.ai_analysis_models import ContextEntry, PartExtraction, SourceReference
from dataforge.ai_context import PreparedAnalysis, SourceSnapshot, plan_file_parts
from dataforge.ai_context_index import build_context_index, context_for_part


def prepared(*sources):
    from dataforge.ai_analysis_models import AnalysisRequest
    return PreparedAnalysis('workspace', AnalysisRequest(mode='ai'), tuple(sources), '{}')


def test_inferred_definition_cannot_disclose_an_unselected_source():
    source = SourceSnapshot('c', 'hc', 'c.sql', '.sql', '', 'select * from a;', 'sql')
    denied = ContextEntry(entry_id='denied', symbol='a', source_kind='sql', origin='ai_inferred',
        evidence=[SourceReference(file_id='unselected', content_hash='hash', start_offset=0, end_offset=1)])
    index = build_context_index(prepared(source), [PartExtraction(part_id='x', definitions=[denied])])
    part = plan_file_parts(source, {}, model())[0]
    selection = context_for_part(index, part, 10000)
    assert not selection.entries
    assert index.denied == ['denied']
    assert 'unselected' not in json.dumps(selection.wire)
