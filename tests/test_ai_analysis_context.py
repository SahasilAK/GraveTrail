import pytest

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_context import PreparedAnalysis, SourceSnapshot, plan_ai_units
from dataforge.llm_resources import context_chunks


def prepared(code, extension='.sql'):
    source = SourceSnapshot(file_id='f',content_hash='h',path='a'+extension,extension=extension,job_id='workspace',code=code)
    return PreparedAnalysis(workspace='w',request=AnalysisRequest(mode='hybrid'),sources=(source,),settings_json='{}')


def test_same_line_units_keep_exact_offsets_and_more_than_50():
    code = ' '.join('select '+str(i)+';' for i in range(60))
    plan = plan_ai_units(prepared(code))
    assert len(plan.units) == 60
    for u in plan.units:
        assert code[u.start_offset:u.end_offset] == u.code
    assert len({u.unit_id for u in plan.units}) == 60


def test_sas_macro_data_and_oversized_blocks_are_whole():
    code = '%macro m; data x; set y; run; %mend;'
    plan = plan_ai_units(prepared(code,'.sas'))
    assert [u.code for u in plan.units] == [code]
    assert plan_ai_units(prepared(code,'.sas'),max_chars=10).blocked


def test_comments_have_explicit_empty_coverage_and_manual_cap_unchanged():
    plan = plan_ai_units(prepared('-- no operations\n/* empty */'))
    assert not plan.units and plan.empty_files == ('f',)
    with pytest.raises(ValueError, match='50 chunks'):
        context_chunks('\n'.join('select '+str(i)+';' for i in range(60)),'.sql',1,60,12)


def test_declared_schema_catalog_has_evidence_and_conflicts_are_unknown():
    plan=plan_ai_units(prepared('create table a (id int, name varchar(20)); select * from a;'))
    schema=[x for x in plan.catalog if x.get('schema_status')=='declared'][0]
    assert schema['columns'][0]['name']=='id' and schema['evidence']['quote'].startswith('create table')
    assert all(x['unit_id'] != plan.units[0].unit_id for x in plan.context_for(plan.units[0]))
    assert any(x.get('schema_status') == 'declared' for x in plan.context_for(plan.units[1]))
    conflicted=plan_ai_units(prepared('create table a (id int); create table a (id varchar(10));'))
    assert all(x['schema_status']=='unresolved' and not x['columns'] for x in conflicted.catalog if 'schema_status' in x)
