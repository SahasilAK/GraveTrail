import asyncio
import json

import httpx
import pytest

from dataforge.agent.contracts import AccessPolicy, AgentError, AgentSettings
from dataforge.agent.mcp_server import create_server
from dataforge.agent.service import AgentService
from dataforge.ingestion import Importer
from dataforge.llm import Profile
from dataforge.services import analyze
from dataforge.store import Store


def test_ai_offline_preview_grounded_request_merge_and_revoke(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('AI')
    code = 'create table mart.x as select id from raw.a;'
    Importer(store, w).files([('q.sql', code.encode())], {'.sql'})
    analyze(store, w)
    fid = store.files(w)[0]['file_id']
    p = Profile(provider='Ollama', base_url='http://localhost:11434', model='manual')
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['profile', w, 'test', p.model_dump_json()])
    store.set_setting(w, 'default_profile', 'profile')
    service = AgentService(store, AccessPolicy(allow_write=True, allow_llm=True, allowed_llm_origins=('http://localhost:11434',)))
    try:
        preview = service.call('ai_chunks', w, file_id=fid, first=1, last=1, task='sql_lineage')
        digest = preview['content_hash']
        payload = {'claims': [{'source': 'raw.a', 'target': 'mart.x', 'operation': 'CREATE', 'start_line': 1,
            'end_line': 1, 'quote': code, 'explanation': 'Explicit source and target', 'confidence': .99}]}
        service.provider_transport = httpx.MockTransport(lambda req: httpx.Response(200, json={'message': {'content': json.dumps(payload)}}))
        server = create_server(service)
        result = asyncio.run(server.call_tool('request_ai_assistance', {'workspace_id': w, 'file_id': fid,
            'first': 1, 'last': 1, 'task': 'sql_lineage', 'expected_hash': digest}))
        assert not result.isError, result
        rid = result.structuredContent['record_id']
        assert result.structuredContent['outcome'] == 'validated'
        first = service.call('ai_merge', w, record_id=rid)
        second = service.call('ai_merge', w, record_id=rid)
        assert first['merged'] == 1 and second['already_merged']
        assert len([e for e in store.edges(w) if e['method'] == 'llm']) == 1
        AgentSettings(allow_source=False).save(store, w)
        metadata = service.call('ai_result', w, record_id=rid)
        assert code not in json.dumps(metadata)
        with pytest.raises(AgentError):
            service.call('ai_result', w, record_id=rid, options={'detail_level': 'detailed'})
    finally:
        service.close()
        store.close()
