import json

import httpx
import pytest

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_context import AIExecutionContext
from dataforge.llm import MANUAL_TASKS, PROJECT_TASKS, Adapter, Profile


def test_physical_attempt_hook_blocks_retry_and_legacy_tuple():
    calls=[]
    def hook(profile):
        if len(calls) >= 1:
            raise InterruptedError('revoked')
        calls.append(profile.model)
    p=Profile(provider='OpenAI compatible',base_url='http://localhost:1234',model='m')
    with Adapter(p,transport=httpx.MockTransport(lambda r:httpx.Response(500)),before_attempt=hook) as adapter:
        with pytest.raises(InterruptedError):
            adapter.complete('system','user')
    assert calls == ['m']


@pytest.mark.parametrize('provider,envelope,finish',[
 ('OpenAI compatible',{'choices':[{'message':{'content':'{}'},'finish_reason':'length'}]},'length'),
 ('Anthropic',{'content':[{'text':'{}'}],'stop_reason':'max_tokens'},'max_tokens'),
 ('Ollama',{'message':{'content':'{}'},'done_reason':'length'},'length'),
 ('Gemini',{'candidates':[{'content':{'parts':[{'text':'{}'}]},'finishReason':'MAX_TOKENS'}]},'MAX_TOKENS')])
def test_completion_metadata_keeps_truncation(provider,envelope,finish):
    p=Profile(provider=provider,base_url='http://localhost:1234',model='m')
    with Adapter(p,transport=httpx.MockTransport(lambda r:httpx.Response(200,json=envelope))) as adapter:
        text,usage=adapter.complete('s','u')
        assert text == '{}'
        assert adapter.completion_metadata['finish_reason'] == finish
        assert adapter.completion_metadata['truncated']
        assert not adapter.completion_metadata['usage_known']


def test_execution_reserves_every_attempt_and_deadline():
    clock=[0.0]
    p=Profile(provider='OpenAI compatible',base_url='http://localhost:1234',model='m',max_tokens=1000)
    execution=AIExecutionContext(AnalysisRequest(mode='hybrid',max_provider_attempts=1),clock=lambda:clock[0])
    execution.before_attempt(p)
    with pytest.raises(ValueError,match='attempt'):
        execution.before_attempt(p)
    clock[0]=1801
    with pytest.raises(TimeoutError):
        execution.check()


def test_hour_timeout_respects_the_remaining_execution_deadline():
    p = Profile(provider='OmniRoute', base_url='http://localhost:20128/v1', model='auto/best-coding', timeout=3600)
    with pytest.raises(ValueError):
        Profile(**{**p.model_dump(), 'timeout': 3601})
    clock = [0.0]
    execution = AIExecutionContext(AnalysisRequest(mode='hybrid', max_seconds=7200), clock=lambda: clock[0])
    assert execution.before_attempt(p) == 3600
    clock[0] = 7100
    assert execution.before_attempt(p) == 100


def test_task_registries_and_generated_schemas():
    from dataforge.llm import PROJECT_SCHEMAS, PROMPTS
    assert len(MANUAL_TASKS)==5 and set(PROJECT_TASKS)=={'project_lineage','lineage_review'}
    for task,model in PROJECT_SCHEMAS.items():
        assert json.loads((PROMPTS/'schemas'/f'{task}_response.json').read_text()) == model.model_json_schema()
        assert (PROMPTS/task/'user_template.md').read_text().count('{{context}}') == 1


def test_invoke_unit_rejects_truncated_empty_and_tracks_unknown_usage(tmp_path):
    from dataforge.ai_context import plan_ai_units, prepare_analysis
    from dataforge.ingestion import Importer
    from dataforge.llm import invoke_analysis_unit
    from dataforge.store import Store
    store=Store(tmp_path)
    workspace=store.create_workspace('test')
    Importer(store,workspace).files([('one.sql',b'select 1;')],{'.sql'})
    profile=Profile(provider='OpenAI compatible',base_url='http://localhost:1234',model='m',context_chars=100000)
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)',['p',workspace,'test',profile.model_dump_json()])
    store.set_setting(workspace,'default_profile','p')
    store.set_setting(workspace,'max_context_chars',100000)
    unit=plan_ai_units(prepare_analysis(store,workspace,AnalysisRequest(mode='hybrid'))).units[0]
    payload={'unit_id':unit.unit_id,'coverage':{'status':'no_operations'}}
    transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(payload)},'finish_reason':'length'}]}))
    result=invoke_analysis_unit(store,workspace,unit,'project_lineage',AIExecutionContext(AnalysisRequest(mode='hybrid'),transport=transport))
    assert result.outcome == 'quarantined' and result.result is None
    assert result.attempts == 1 and not result.usage_known
    store.close()


def test_attempt_ceiling_blocks_fallback_and_offline_preview(tmp_path):
    from dataforge.ai_context import plan_ai_units, prepare_analysis
    from dataforge.ingestion import Importer
    from dataforge.llm import invoke_analysis_unit, preview_analysis_routes
    from dataforge.store import Store
    store=Store(tmp_path)
    w=store.create_workspace('budget')
    Importer(store,w).files([('one.sql',b'select 1;')],{'.sql'})
    p=Profile(provider='OpenAI compatible',base_url='http://localhost:1234',model='m',context_chars=100000,retries=1,max_tokens=1000)
    for pid in ['p','fallback']:
        store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)',[pid,w,pid,p.model_dump_json()])
    store.set_setting(w,'default_profile','p')
    store.set_setting(w,'fallback_profiles',['fallback'])
    store.set_setting(w,'max_context_chars',100000)
    request=AnalysisRequest(mode='hybrid',max_provider_attempts=2)
    units=plan_ai_units(prepare_analysis(store,w,request)).units
    calls=[]
    transport=httpx.MockTransport(lambda r:(calls.append(r),httpx.Response(429))[1])
    execution=AIExecutionContext(request,transport=transport)
    preview=preview_analysis_routes(store,w,units,execution)
    assert not calls and not preview['valid'] and preview['max_provider_attempts']==4
    result=invoke_analysis_unit(store,w,units[0],'project_lineage',execution)
    assert len(calls)==2 and execution.attempts==2 and result.outcome=='quarantined'
    store.close()


@pytest.mark.parametrize('envelope',[{'choices':[None]},{'choices':'bad'},{'choices':[]}])
def test_malformed_protocol_envelope_is_provider_error(envelope):
    from dataforge.llm import ProviderError
    p=Profile(provider='OpenAI compatible',base_url='http://localhost:1234',model='m')
    with Adapter(p,transport=httpx.MockTransport(lambda r:httpx.Response(200,json=envelope))) as adapter:
        with pytest.raises(ProviderError):
            adapter.complete('s','u')


def test_offline_preview_detects_missing_configured_credential(tmp_path):
    from dataforge.llm import preview_analysis_routes
    class Store:
        def rows(self,sql,args):
            p=Profile(provider='OpenAI compatible',base_url='http://localhost:1234',model='m',key_env='UNAVAILABLE_PROJECT_TEST_REFERENCE')
            return [{'profile_id':'p','config':p.model_dump_json()}]
        def setting(self,w,key,default=None):
            return {'default_profile':'p'}.get(key,default)
    result=preview_analysis_routes(Store(),'w',[],AIExecutionContext(AnalysisRequest(mode='hybrid')))
    assert any(x['reason']=='credential_unavailable' for x in result['blocked'])


def test_default_context_accepts_short_unit_without_loosening_limits(tmp_path):
    from dataforge.analysis_service import preview_analysis
    from dataforge.ingestion import Importer
    from dataforge.store import Store
    store=Store(tmp_path)
    try:
        w=store.create_workspace('default context')
        Importer(store,w).files([('short.sql',b'create table b as select id from a;')],{'.sql'})
        p=Profile(provider='OpenAI compatible',base_url='http://localhost:1234',model='m')
        store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)',['p',w,'default',p.model_dump_json()])
        store.set_setting(w,'default_profile','p')
        preview=preview_analysis(store,w,AnalysisRequest(mode='hybrid'))
        assert preview['valid'],preview['blocked']
        assert store.setting(w,'max_context_chars',8000)==8000
        assert p.context_chars==16000
    finally:
        store.close()


def test_transmitted_schema_is_compact_but_preserves_validation_contract():
    import hashlib

    from dataforge.ai_analysis_models import AnalysisUnit
    from dataforge.llm import PROJECT_SCHEMAS, PROMPTS, analysis_prompt
    unit=AnalysisUnit(unit_id='u',file_id='f',content_hash='h',path='s.sql',extension='.sql',
        first=1,last=1,start_offset=0,end_offset=9,code='select 1;')
    system,user,digest=analysis_prompt(unit,'project_lineage',AIExecutionContext(AnalysisRequest(mode='hybrid')))
    template=(PROMPTS/'project_lineage'/'user_template.md').read_text(encoding='utf-8')
    context=json.loads(user.split('\n\n',1)[1])
    schema=context['schema']
    assert 'title' not in schema and 'title' not in schema['$defs']['Coverage']
    assert 'default' not in schema['properties']['relationships']
    assert schema['additionalProperties'] is False
    assert schema['properties']['relationships']['maxItems']==100
    assert schema['$defs']['EvidenceReference']['properties']['unit_id']['maxLength']==500
    assert 'quote' not in schema['$defs']['EvidenceReference']['properties']
    assert schema['$defs']['Coverage']['properties']['status']['enum']==['complete','partial','unsupported','no_operations']
    assert schema['required']==PROJECT_SCHEMAS['project_lineage'].model_json_schema()['required']
    assert json.dumps(context,ensure_ascii=False,separators=(',',':')) in user
    assert digest==hashlib.sha256((system+template+json.dumps(schema,sort_keys=True,separators=(',',':'))).encode()).hexdigest()


def test_compaction_preserves_annotation_named_properties_and_context_ceiling(tmp_path):
    from dataforge.ai_analysis_models import AnalysisUnit
    from dataforge.llm import _transmitted_schema, analysis_prompt, preview_analysis_routes
    original={'title':'Object','properties':{'title':{'type':'string','title':'Title','maxLength':7},
        'default':{'type':'integer','default':2,'minimum':1}},'$defs':{'title':{'type':'number','description':'Value'}}}
    assert _transmitted_schema(original)=={'properties':{'title':{'type':'string','maxLength':7},
        'default':{'type':'integer','minimum':1}},'$defs':{'title':{'type':'number'}}}
    code='select 1;'+(' '*3000)
    unit=AnalysisUnit(unit_id='u',file_id='f',content_hash='h',path='s.sql',extension='.sql',
        first=1,last=1,start_offset=0,end_offset=len(code),code=code)
    p=Profile(provider='OpenAI compatible',base_url='http://localhost:1234',model='m')
    class Store:
        def rows(self,sql,args):
            return [{'profile_id':'p','config':p.model_dump_json()}]
        def setting(self,w,key,default=None):
            return {'default_profile':'p'}.get(key,default)
    execution=AIExecutionContext(AnalysisRequest(mode='hybrid'))
    system,user,_=analysis_prompt(unit,'project_lineage',execution)
    assert len(code)<8000<len(system)+len(user)
    result=preview_analysis_routes(Store(),'w',[unit],execution)
    assert result['valid']  # Fixed protocol/schema overhead is not disclosed source.
    execution.request = execution.request.model_copy(update={'max_context_chars': 2000})
    result = preview_analysis_routes(Store(),'w',[unit],execution)
    assert not result['valid'] and result['blocked'][0]['reason']=='source_context_exceeds_character_allowance'


def test_schema_compaction_keeps_literal_values_and_dependency_property_names():
    from dataforge.llm import _transmitted_schema
    schema={'title':'Annotation','const':{'title':'literal','default':5},
        'enum':[{'description':'literal'}],'dependentRequired':{'default':['title']}}
    assert _transmitted_schema(schema)=={'const':{'title':'literal','default':5},
        'enum':[{'description':'literal'}],'dependentRequired':{'default':['title']}}


def test_rejected_wire_input_never_leaks_into_default_history(tmp_path):
    from dataforge.analysis_service import run_analysis
    from dataforge.ingestion import Importer
    from dataforge.store import Store
    store = Store(tmp_path)
    w = store.create_workspace('rejected-body privacy')
    Importer(store, w).files([('q.sql', b'select 1;')], {'.sql'})
    p = Profile(provider='Ollama', base_url='http://localhost:11434', model='m', context_chars=100000, retries=0)
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', w, 'm', p.model_dump_json()])
    store.set_setting(w, 'default_profile', 'p')
    store.set_setting(w, 'max_context_chars', 100000)
    marker = 'REJECTED_MODEL_TEXT_DO_NOT_RETAIN'
    def respond(request):
        text = json.loads(request.content)['messages'][-1]['content']
        context = json.loads(text[text.index('{'):])
        payload = {'unit_id': context['unit']['unit_id'], 'relationships': [{'source': 'a', 'target': 'b',
            'operation': 'CREATE', 'evidence': {'unit_id': context['unit']['unit_id'], 'quote': marker}}]}
        return httpx.Response(200, json={'message': {'content': json.dumps(payload)}})
    result = run_analysis(store, w, AnalysisRequest(mode='hybrid'), transport=httpx.MockTransport(respond))
    assert result.status == 'failed'
    assert marker not in str(store.rows('SELECT details FROM llm_records'))
    store.close()


def test_small_fallback_is_excluded_and_never_receives_an_oversized_request(tmp_path):
    from dataforge.ai_context import plan_ai_units, prepare_analysis
    from dataforge.analysis_service import preview_analysis
    from dataforge.ingestion import Importer
    from dataforge.llm import invoke_analysis_unit
    from dataforge.model_capabilities import ModelCapabilities, bind_capabilities
    from dataforge.store import Store
    store = Store(tmp_path)
    w = store.create_workspace('Constrained fallback')
    Importer(store, w).files([('q.sql', b'select 1;')], {'.sql'})
    primary = Profile(provider='OpenAI compatible', base_url='http://localhost:1234', model='primary',
        retries=0, context_chars=100000)
    fallback = primary.model_copy(update={'model': 'fallback'})
    fallback.model_capabilities = bind_capabilities(ModelCapabilities(context_tokens=4000), fallback)
    for pid, profile in [('p', primary), ('f', fallback)]:
        store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', [pid, w, pid, profile.model_dump_json()])
    store.set_setting(w, 'default_profile', 'p')
    store.set_setting(w, 'fallback_profiles', ['f'])
    store.set_setting(w, 'max_context_chars', 100000)
    request = AnalysisRequest(mode='hybrid')
    preview = preview_analysis(store, w, request)
    assert preview['valid'] and preview['max_provider_attempts'] == 1
    assert preview['excluded_routes'][0]['profile_id'] == 'f'
    unit = plan_ai_units(prepare_analysis(store, w, request)).units[0]
    sent = []
    def respond(r):
        sent.append(json.loads(r.content)['model'])
        return httpx.Response(503)
    result = invoke_analysis_unit(store, w, unit, 'project_lineage',
        AIExecutionContext(request, transport=httpx.MockTransport(respond)))
    assert result.outcome == 'quarantined' and sent == ['primary']
    store.close()
