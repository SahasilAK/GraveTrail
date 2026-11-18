"""Lossless file ranges and output pressure replace source/context products."""
from dataclasses import replace

import pytest
from test_ai_file_parts import source
from test_ai_token_budget import model

from dataforge.ai_batching import pack_request
from dataforge.ai_context import plan_file_parts


@pytest.mark.parametrize('family', ['sas', 'dbt'])
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
