from contextlib import closing

import pytest

from dataforge.agent.contracts import AgentError
from dataforge.agent.service import AgentService
from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


def setup_store(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('dbt reports')
    store.set_setting(w, 'agent_enabled', True)
    Importer(store, w).files([('dbt_project.yml', b'name: shop'),
        ('models/a.sql', b"select {{ money('id') }} as amount from {{ ref('b') }}"),
        ('models/b.sql', b'select 1 as id'),
        ('macros/money.sql', b'{% macro money(x) %}{{ x }}/100{% endmacro %}')], set(), source_kind='dbt')
    analyze(store, w)
    return store, w


def test_shared_reports_list_resources_and_trace_macro_consumers(tmp_path):
    store, w = setup_store(tmp_path)
    with closing(store), closing(AgentService(store)) as service:
        projects = service.call('dbt_projects', w)
        assert projects['items'][0]['package_name'] == 'shop'
        pid = projects['items'][0]['project_id']
        resources = service.call('dbt_resources', w, project_id=pid)
        macro = next(r for r in resources['items'] if r['resource_type'] == 'macro')
        impact = service.call('dbt_dependencies', w, resource_id=macro['resource_id'], direction='downstream')
        assert any(r['kind'] == 'macro_call' for r in impact['items'])
        detail = service.call('dbt_resource', w, resource_id=macro['resource_id'])
        assert 'evidence' not in detail
        store.set_setting(w, 'agent_access', {'allow_source': False})
        with pytest.raises(AgentError):
            service.call('dbt_resource', w, options={'detail_level': 'detailed'}, resource_id=macro['resource_id'])


def test_queries_reject_cross_workspace_resource_and_unsupported_direction(tmp_path):
    store, w = setup_store(tmp_path)
    with closing(store), closing(AgentService(store)) as service:
        other = store.create_workspace('other')
        store.set_setting(other, 'agent_enabled', True)
        rid = store.rows('SELECT resource_id FROM dbt_resources LIMIT 1')[0]['resource_id']
        with pytest.raises(AgentError):
            service.call('dbt_resource', other, resource_id=rid)
        with pytest.raises(AgentError):
            service.call('dbt_dependencies', w, resource_id=rid, direction='sideways')
