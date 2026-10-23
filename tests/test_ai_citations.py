"""Host source references remove model offset arithmetic without granting semantic rights."""
import hashlib

import pytest

from dataforge.ai_analysis_models import AnalysisUnit, ValidationContext
from dataforge.ai_citations import source_references
from dataforge.ai_validation import validate_project_response
from dataforge.ai_wire import decode_project_result, encode_project_result


def unit(code, extension='.sql', **changes):
    return AnalysisUnit(unit_id='u', file_id='f', content_hash=hashlib.sha256(code.encode()).hexdigest(),
                        path='example' + extension, extension=extension, job_id='job',
                        first=1, last=code.count('\n') + 1, start_offset=0, end_offset=len(code), code=code, **changes)


def payload(u, ref, **changes):
    return {'unit_id': u.unit_id, 'derivations': [{'target_table': 'mart.b', 'target_column': 'x',
            'category': 'direct', 'expression_reference': ref['reference_id'], 'ordinal': 0,
            'inputs': [{'table': 'raw.a', 'column': 'x'}], 'evidence': {'unit_id': u.unit_id}, **changes}]}


def test_repeated_projection_text_resolves_exact_occurrence_and_preserves_legacy_roundtrip():
    u = unit('CREATE TABLE mart.b AS SELECT a.x FROM raw.a a UNION ALL SELECT a.x FROM raw.c a;')
    refs = [r for r in source_references(u) if r['kind'] == 'projection']
    assert [r['text'] for r in refs] == ['a.x', 'a.x']
    assert refs[0]['reference_id'] != refs[1]['reference_id']
    result = decode_project_result('project_lineage', payload(u, refs[1], branch=1,
        inputs=[{'table': 'raw.c', 'column': 'x'}]), u)
    claim = result.derivations[0]
    assert claim.expression_start_offset == u.code.rindex('a.x')
    assert claim.expression == 'a.x'
    assert decode_project_result('project_lineage', encode_project_result(result), u) == result
    report = validate_project_response(result, ValidationContext(unit=u, source_text=u.code))
    assert len(report.accepted) == 1


@pytest.mark.parametrize('change', [{'expression_reference': 'forged'}, {'expression': 'a.y'},
                                    {'expression_start_offset': 0, 'expression_end_offset': 3}])
def test_reference_conflicts_never_override_source_or_supplied_evidence(change):
    u = unit('CREATE TABLE mart.b AS SELECT a.x FROM raw.a a;')
    ref = next(r for r in source_references(u) if r['kind'] == 'projection')
    with pytest.raises(ValueError):
        decode_project_result('project_lineage', payload(u, ref, **change), u)


def test_reference_is_bound_to_source_hash_job_unit_and_actual_text():
    u = unit('CREATE TABLE mart.b AS SELECT a.x FROM raw.a a;')
    ref = next(r for r in source_references(u) if r['kind'] == 'projection')
    for changes in ({'unit_id': 'other'}, {'content_hash': 'changed'}, {'job_id': 'other'},
                    {'code': u.code.replace('a.x', 'a.y')}):
        other = u.model_copy(update=changes)
        data = payload(other, ref)
        with pytest.raises(ValueError):
            decode_project_result('project_lineage', data, other)


def test_correct_source_reference_cannot_prove_wrong_dependency_owner():
    u = unit('CREATE TABLE mart.b AS SELECT a.x FROM raw.a a;')
    ref = next(r for r in source_references(u) if r['kind'] == 'projection')
    result = decode_project_result('project_lineage', payload(u, ref,
        inputs=[{'table': 'raw.c', 'column': 'x'}]), u)
    report = validate_project_response(result, ValidationContext(unit=u, source_text=u.code))
    assert not report.accepted and report.rejected


def test_identical_union_expression_reference_cannot_switch_branches():
    u = unit('CREATE TABLE mart.b AS SELECT a.x FROM raw.a a UNION ALL SELECT a.x FROM raw.c a;')
    refs = [r for r in source_references(u) if r['kind'] == 'projection']
    result = decode_project_result('project_lineage', payload(u, refs[1]), u)
    report = validate_project_response(result, ValidationContext(unit=u, source_text=u.code))
    assert not report.accepted and report.rejected


def test_repeated_sas_assignment_reference_cannot_switch_versions():
    u = unit('data mart.b; set raw.a; x=x+1; x=x+1; run;', '.sas')
    refs = [r for r in source_references(u) if r['kind'] == 'assignment']
    for reference, accepted in [(refs[0], False), (refs[1], True)]:
        result = decode_project_result('project_lineage', payload(u, reference, scope='data-step',
            version='2', ordinal=1, category='expression',
            inputs=[{'table': 'mart.b', 'column': 'x', 'scope': 'data-step', 'version': '1'}]), u)
        report = validate_project_response(result, ValidationContext(unit=u, source_text=u.code))
        assert bool(report.accepted) is accepted


def test_sas_assignment_and_dml_rhs_use_complete_original_text():
    sas = unit('data mart.b; set raw.a; /* exact */ x = x + 1; x = x + 1; run;', '.sas')
    refs = [r for r in source_references(sas) if r['kind'] == 'assignment']
    assert len(refs) == 2 and '/* exact */' in refs[0]['text']
    sql = unit('UPDATE mart.b SET x = (a.x + 1), y = a.x FROM raw.a a WHERE mart.b.id=a.id;')
    rhs = [r for r in source_references(sql) if r['kind'] == 'assignment']
    assert [r['text'] for r in rhs] == ['(a.x + 1)', 'a.x']


def test_projection_refs_preserve_unicode_comments_and_hide_omitted_focus():
    from dataforge.ai_semantic import split_projection_unit
    u = unit('CREATE TABLE mart.b AS SELECT a.x AS one, /* café */ a.y AS two FROM raw.a a;')
    left, right = split_projection_unit(u)
    refs = source_references(right)
    assert not any(r['text'] == 'a.x AS one' for r in refs)
    projection = next(r for r in refs if r['kind'] == 'projection')
    assert projection['text'] == '/* café */ a.y AS two'
    start, end = projection['start_offset'], projection['end_offset']
    assert u.code[start:end] == projection['text']
    foreign = next(r for r in source_references(left) if r['kind'] == 'projection')
    with pytest.raises(ValueError):
        decode_project_result('project_lineage', payload(right, foreign), right)


def test_dialect_specific_reference_uses_absolute_original_coordinates():
    code = 'CREATE TABLE mart.b AS SELECT a.x AS [value] FROM raw.a a;'
    u = unit(code).model_copy(update={'start_offset': 93, 'end_offset': 93 + len(code)})
    settings = {'dialect_by_extension': {'.sql': 'tsql'}}
    ref = next(r for r in source_references(u, settings) if r['kind'] == 'projection')
    claim = decode_project_result('project_lineage', payload(u, ref, target_column='value'),
                                  u, settings=settings).derivations[0]
    assert claim.expression == 'a.x AS [value]'
    assert claim.expression_start_offset == 93 + code.index('a.x')
    with pytest.raises(ValueError):
        decode_project_result('project_lineage', payload(u, ref), u)


def test_malformed_sql_does_not_issue_guessed_expression_references():
    assert source_references(unit('SELECT ( FROM ;')) == []


def test_static_proc_sql_pages_retain_projection_references_and_absolute_offsets():
    from dataforge.ai_semantic import split_proc_sql_unit
    u = unit('proc sql; create table mart.b as select a.x from raw.a a; '
             'create table mart.c as select a.y from raw.a a; quit;', '.sas')
    pages = split_proc_sql_unit(u)
    assert len(pages) == 2
    for page, expression in zip(pages, ['a.x', 'a.y']):
        ref = next(r for r in source_references(page) if r['kind'] == 'projection')
        assert ref['text'] == expression
        claim = decode_project_result('project_lineage', payload(page, ref), page).derivations[0]
        assert claim.expression_start_offset == u.code.index(expression)


def test_sas_format_projection_references_survive_generic_sql_parse_failure():
    u = unit('proc sql; create table mart.b as select a.x format=$char10. as x from raw.a a; quit;', '.sas')
    ref = next(r for r in source_references(u) if r['kind'] == 'projection')
    assert ref['text'] == 'a.x format=$char10. as x'
    claim = decode_project_result('project_lineage', payload(u, ref), u)
    report = validate_project_response(claim, ValidationContext(unit=u, source_text=u.code))
    assert len(report.accepted) == 1
