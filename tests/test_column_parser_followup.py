"""Nested query repairs and deliberately bounded PostgreSQL writes."""
import json
from contextlib import closing

from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store
from dataforge.transformations import trace_columns


def test_nested_modifier_stays_incomplete_after_persistence(tmp_path):
    sql = 'CREATE TABLE dst AS (SELECT a FROM src UNION ALL SELECT a FROM other LIMIT 1) UNION ALL SELECT a FROM third'
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('persist modifiers')
        Importer(store, workspace).files([('nested.sql', sql.encode())], {'.sql'})
        analyze(store, workspace)
        target = next(a['asset_id'] for a in store.assets(workspace) if a['name'] == 'dst')
        result = trace_columns(store, workspace, target, 'a')
        assert not result['complete']
        assert sum(d['status'] == 'unresolved' for d in result['derivations']) == 2


def test_mutation_prior_values_are_isolated_across_operations_and_reopen(tmp_path):
    path = tmp_path / 'home'
    with closing(Store(path)) as store:
        workspace = store.create_workspace('writes')
        store.set_setting(workspace, 'dialect', 'postgres')
        sql = 'UPDATE t SET a=b, b=a WHERE active=1; UPDATE t SET a=c; INSERT INTO t(a) VALUES (5)'
        Importer(store, workspace).files([('writes.sql', sql.encode())], {'.sql'})
        analyze(store, workspace)
        target = next(a['asset_id'] for a in store.assets(workspace) if a['name'] == 't')
        result = trace_columns(store, workspace, target, 'a', include_source=True)
        assert not result['complete'] and len(result['derivations']) == 3
        assert any(c['reason'] == 'multiple_writers' for c in result['coverage'])
        targets = {d['target']['column_id'] for d in result['derivations']}
        prior = [i for d in result['derivations'] for i in d['inputs']]
        assert all(i['column_id'] not in targets and i['scope'] == 'update:prior' and i['version'] == 'prior' for i in prior)
        assert len({i['column_id'] for i in prior if i['role'] == 'rowset'}) == 2
        prior_trace = trace_columns(store, workspace, target, prior[0]['column_id'])
        assert not prior_trace['complete']
        assert any(c['reason'] == 'unresolved_scope' for c in prior_trace['coverage'])
        assert all(sql.find(d['expression']) >= 0 and d['evidence']['source_hash'] for d in result['derivations'])
        assert not any(c['reason'] == 'cycle' for c in result['coverage'])
        assert not trace_columns(store, workspace, target, 'untouched')['complete']
        identities = {d['derivation_id'] for d in result['derivations']}
        assert analyze(store, workspace)['analyzed'] == 0
    with closing(Store(path)) as store:
        reopened = trace_columns(store, workspace, target, 'a', include_source=True)
        assert {d['derivation_id'] for d in reopened['derivations']} == identities
        analyze(store, workspace, force=True)
        assert {d['derivation_id'] for d in trace_columns(store, workspace, target, 'a')['derivations']} == identities


def test_previous_parser_cache_reanalysis_publishes_literal_targets(tmp_path, monkeypatch):
    from dataforge import services

    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('parser upgrade')
        store.set_setting(workspace, 'dialect', 'postgres')
        Importer(store, workspace).files([('row.sql', b'INSERT INTO t(a) VALUES (NULL)')], {'.sql'})
        with monkeypatch.context() as previous:
            previous.setattr(services, 'PARSER_VERSION', '16')
            analyze(store, workspace)
        target = next(a['asset_id'] for a in store.assets(workspace) if a['name'] == 't')
        stale = trace_columns(store, workspace, target, 'a')
        assert any(c['reason'] == 'reanalysis_required' for c in stale['coverage'])
        refreshed = analyze(store, workspace)
        assert refreshed['analyzed'] == 1 and refreshed['cached'] == 0
        result = trace_columns(store, workspace, target, 'a')
        assert len(result['derivations']) == 1 and result['derivations'][0]['expression'] == 'NULL'
        assert not result['complete']
        assert not any(c['reason'] == 'reanalysis_required' for c in result['coverage'])


def test_bounded_mutations_preserve_scene_evidence_and_agent_redaction(tmp_path):
    from dataforge.agent.service import AgentService
    from dataforge.column_evidence import load_column_evidence
    from dataforge.column_graph import build_column_scene

    sql = "UPDATE t SET a=b WHERE active=1; INSERT INTO t(a) VALUES ('PRIVATE_LITERAL_415')"
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('mutation boundaries')
        store.set_setting(workspace, 'dialect', 'postgres')
        Importer(store, workspace).files([('writes.sql', sql.encode())], {'.sql'})
        analyze(store, workspace)
        target = next(a['asset_id'] for a in store.assets(workspace) if a['name'] == 't')
        result = trace_columns(store, workspace, target, 'a')
        scene = build_column_scene(result, result['derivations'][0]['target'])
        assert not scene['trace_complete']
        assert {n['derivation_id'] for n in scene['nodes'] if n['kind'] == 'transformation'} == {
            d['derivation_id'] for d in result['derivations']}
        assert 'PRIVATE_LITERAL_415' not in json.dumps(scene)
        columns = [n['id'] for n in scene['nodes'] if n['kind'] == 'column']
        assert len(columns) == len(set(columns)) == 4
        for derivation in result['derivations']:
            detail = load_column_evidence(store, workspace, result['run_id'], derivation['derivation_id'], include_file=True)
            assert detail['expression'] == derivation['expression']
            assert detail['file']['raw_content'] == sql
            assert detail['file']['content_hash'] == derivation['evidence']['source_hash']
        with closing(AgentService(store)) as service:
            store.set_setting(workspace, 'agent_access', {'allow_source': False})
            summary = service.call('column_lineage', workspace, asset='t', column='a')
            assert len(summary['items']) == 2
            assert all('expression' not in d and 'code' not in d['evidence'] for d in summary['items'])
            assert 'PRIVATE_LITERAL_415' not in json.dumps(summary)
