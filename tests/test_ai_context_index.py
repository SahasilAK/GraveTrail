import json

from test_ai_token_budget import model

from dataforge.ai_analysis_models import ContextEntry, PartExtraction, SourceReference
from dataforge.ai_context import PreparedAnalysis, SourceSnapshot, plan_file_parts
from dataforge.ai_context_index import build_context_index, context_for_part


def prepared(*sources):
    from dataforge.ai_analysis_models import AnalysisRequest
    return PreparedAnalysis('workspace', AnalysisRequest(mode='ai'), tuple(sources), '{}')


def test_exact_scope_and_conflicting_definitions_are_explicit():
    consumer = SourceSnapshot('c', 'hc', 'c.sql', '.sql', 'job', 'select * from raw.a;', 'sql')
    definition = SourceSnapshot('d', 'hd', 'd.sql', '.sql', 'job', 'create table raw.a(id int);', 'sql')
    other = SourceSnapshot('e', 'he', 'e.sql', '.sql', 'other', 'create table other.a(id int);', 'sql')
    index = build_context_index(prepared(consumer, definition, other), [])
    part = plan_file_parts(consumer, {}, model())[0]
    selection = context_for_part(index, part, 10000)
    assert [e.symbol for e in selection.entries] == ['raw.a']
    assert selection.entries[0].origin == 'source_declared'
    duplicate = SourceSnapshot('dup', 'hdup', 'dup.sql', '.sql', 'job', definition.code, 'sql')
    conflicting = context_for_part(build_context_index(prepared(consumer, definition, duplicate), []), part, 10000)
    assert not conflicting.entries
    assert 'raw.a' in conflicting.unresolved
    assert context_for_part(index, part, 1).omitted


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


def test_quoted_names_preserve_case_and_comments_do_not_declare_symbols():
    consumer = SourceSnapshot('c', 'hc', 'c.sql', '.sql', '', 'select * from "Raw"."A";', 'sql')
    declared = SourceSnapshot('d', 'hd', 'd.sql', '.sql', '', 'create table "Raw"."A"(id int);', 'sql')
    fake = SourceSnapshot('f', 'hf', 'f.sql', '.sql', '', '-- create table "Raw"."A"(forged int);\nselect 1;', 'sql')
    selection = context_for_part(build_context_index(prepared(consumer, declared, fake), []),
                                 plan_file_parts(consumer, {}, model())[0], 10000)
    assert [e.evidence[0].file_id for e in selection.entries] == ['d']


def test_dbt_context_index_supplies_relevant_project_definition():
    definition = SourceSnapshot('d', 'hd', 'models/base.sql', '.sql', 'project', 'select 1 as id', 'dbt')
    resource = {'resource_id': 'base-resource', 'name': 'base', 'package_name': 'pkg',
                'project_id': 'project', 'resource_type': 'model', 'definition': {'source': {'file_id': 'd'}}}
    consumer = SourceSnapshot('c', 'hc', 'models/use.sql', '.sql', 'project', "select * from {{ ref('base') }}", 'dbt',
                               json.dumps({'resources': [resource], 'project_id': 'project'}))
    selection = context_for_part(build_context_index(prepared(consumer, definition), []),
                                 plan_file_parts(consumer, {}, model())[0], 10000)
    assert [e.entry_id for e in selection.entries] == ['base-resource']
