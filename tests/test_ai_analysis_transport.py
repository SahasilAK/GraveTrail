import json

import httpx
import pytest

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






def test_task_registries_and_generated_schemas():
    from dataforge.llm import PROJECT_SCHEMAS, PROMPTS
    assert len(MANUAL_TASKS)==5 and set(PROJECT_TASKS)=={'project_lineage'}
    for task,model in PROJECT_SCHEMAS.items():
        assert json.loads((PROMPTS/'schemas'/f'{task}_response.json').read_text()) == model.model_json_schema()
        assert (PROMPTS/task/'extract.md').is_file()






@pytest.mark.parametrize('envelope',[{'choices':[None]},{'choices':'bad'},{'choices':[]}])
def test_malformed_protocol_envelope_is_provider_error(envelope):
    from dataforge.llm import ProviderError
    p=Profile(provider='OpenAI compatible',base_url='http://localhost:1234',model='m')
    with Adapter(p,transport=httpx.MockTransport(lambda r:httpx.Response(200,json=envelope))) as adapter:
        with pytest.raises(ProviderError):
            adapter.complete('s','u')










def test_schema_compaction_keeps_literal_values_and_dependency_property_names():
    from dataforge.llm import _transmitted_schema
    schema={'title':'Annotation','const':{'title':'literal','default':5},
        'enum':[{'description':'literal'}],'dependentRequired':{'default':['title']}}
    assert _transmitted_schema(schema)=={'const':{'title':'literal','default':5},
        'enum':[{'description':'literal'}],'dependentRequired':{'default':['title']}}
