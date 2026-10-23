from dataclasses import replace

from test_ai_context_index import prepared
from test_ai_token_budget import model

from dataforge.ai_context import SourceSnapshot, plan_file_parts
from dataforge.ai_context_index import build_context_index, context_for_part


def test_unrelated_source_does_not_change_relevant_context_but_definition_does():
    query = SourceSnapshot('q', 'h', 'q.sql', '.sql', 'w', 'select id from raw.a;', 'sql')
    definition = SourceSnapshot('d', 'hd', 'd.sql', '.sql', 'w', 'create table raw.a(id int);', 'sql')
    part = plan_file_parts(query, {}, model())[0]
    original = context_for_part(build_context_index(prepared(query, definition), []), part, 10000)
    unrelated = replace(query, file_id='other', code='select * from irrelevant;')
    assert context_for_part(build_context_index(prepared(query, definition, unrelated), []), part, 10000).fingerprint == original.fingerprint
    changed = replace(definition, content_hash='new', code='create table raw.a(id int, name text);')
    assert context_for_part(build_context_index(prepared(query, changed), []), part, 10000).fingerprint != original.fingerprint


def test_repeated_read_sites_do_not_duplicate_disclosed_definitions():
    query = SourceSnapshot('q', 'h', 'q.sql', '.sql', 'w', 'select id from raw.a; ' * 200, 'sql')
    definition = SourceSnapshot('d', 'hd', 'd.sql', '.sql', 'w', 'create table raw.a(id int);', 'sql')
    part = plan_file_parts(query, {}, model())[0]
    selection = context_for_part(build_context_index(prepared(query, definition), []), part, 10000)
    assert len(selection.entries) == 1
    assert selection.wire[0]['source'] == definition.code
