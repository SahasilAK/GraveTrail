import pytest
from test_ai_file_parts import source
from test_ai_token_budget import model

from dataforge.ai_context import plan_file_parts
from dataforge.llm_resources import context_chunks


def test_whole_file_preferred_over_sixty_statement_units():
    text = source(' '.join(f'select {i};' for i in range(60)))
    parts = plan_file_parts(text, {}, model())
    assert len(parts) == 1
    assert parts[0].start_offset == 0 and parts[0].end_offset == len(text.code)


def test_comments_and_empty_files_still_have_explicit_processing_coverage():
    for code in ('-- no operations\n/* empty */', ''):
        parts = plan_file_parts(source(code), {}, model())
        assert len(parts) == 1 and parts[0].end_offset == len(code)
    with pytest.raises(ValueError, match='50 chunks'):
        context_chunks('\n'.join(f'select {i};' for i in range(60)), '.sql', 1, 60, 12)
