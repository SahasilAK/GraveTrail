"""Schema and normalized snapshot persistence, owned transactionally by Store."""
import json
from dataclasses import asdict

from dataforge.dbt.models import DbtLimits, DbtProjectResult
from dataforge.models import stable_id

DBT_CURRENT_TABLES = ('dbt_evidence', 'dbt_relationships', 'dbt_relation_bindings', 'dbt_resources', 'dbt_projects')
DBT_TABLES = (*DBT_CURRENT_TABLES, 'dbt_project_snapshots')
DBT_SCHEMA = '''
CREATE TABLE IF NOT EXISTS dbt_projects(workspace_id VARCHAR, project_id VARCHAR, run_id VARCHAR,
    root_path VARCHAR, package_name VARCHAR, fingerprint VARCHAR, context_json VARCHAR,
    coverage_json VARCHAR, PRIMARY KEY(workspace_id,project_id));
CREATE TABLE IF NOT EXISTS dbt_resources(workspace_id VARCHAR, resource_id VARCHAR, project_id VARCHAR,
    run_id VARCHAR, unique_id VARCHAR, resource_type VARCHAR, package_name VARCHAR, name VARCHAR,
    version VARCHAR, enabled BOOLEAN, asset_id VARCHAR, metadata_json VARCHAR,
    PRIMARY KEY(workspace_id,resource_id));
CREATE TABLE IF NOT EXISTS dbt_relationships(workspace_id VARCHAR, relationship_id VARCHAR, project_id VARCHAR,
    run_id VARCHAR, source_id VARCHAR, target_id VARCHAR, kind VARCHAR, status VARCHAR,
    PRIMARY KEY(workspace_id,relationship_id));
CREATE TABLE IF NOT EXISTS dbt_relation_bindings(workspace_id VARCHAR, binding_id VARCHAR, project_id VARCHAR,
    resource_id VARCHAR, context_id VARCHAR, database_name VARCHAR, schema_name VARCHAR,
    identifier VARCHAR, quoting_json VARCHAR, status VARCHAR, PRIMARY KEY(workspace_id,binding_id));
CREATE TABLE IF NOT EXISTS dbt_evidence(workspace_id VARCHAR, evidence_id VARCHAR, project_id VARCHAR,
    run_id VARCHAR, owner_type VARCHAR, owner_id VARCHAR, file_id VARCHAR, content_hash VARCHAR,
    start_line INTEGER, end_line INTEGER, start_offset BIGINT, end_offset BIGINT,
    json_pointer VARCHAR, excerpt VARCHAR, origin VARCHAR, PRIMARY KEY(workspace_id,evidence_id));
CREATE TABLE IF NOT EXISTS dbt_project_snapshots(workspace_id VARCHAR, run_id VARCHAR, project_id VARCHAR,
    fingerprint VARCHAR, payload_json VARCHAR, PRIMARY KEY(workspace_id,run_id,project_id));
CREATE INDEX IF NOT EXISTS dbt_resource_project ON dbt_resources(workspace_id,project_id,unique_id);
CREATE INDEX IF NOT EXISTS dbt_relationship_source ON dbt_relationships(workspace_id,source_id,kind);
CREATE INDEX IF NOT EXISTS dbt_relationship_target ON dbt_relationships(workspace_id,target_id,kind);
CREATE INDEX IF NOT EXISTS dbt_evidence_owner ON dbt_evidence(workspace_id,owner_type,owner_id);
CREATE INDEX IF NOT EXISTS dbt_evidence_source ON dbt_evidence(file_id,content_hash);
'''


def stage_dbt_rows(result: DbtProjectResult, run_id: str, workspace: str, settings=None) -> dict[str, list]:
    snapshot, rows = result.snapshot, {t: [] for t in DBT_TABLES}
    pid = snapshot.project_id
    payload = json.dumps(result.to_dict(), ensure_ascii=False)
    if len(payload.encode()) > DbtLimits().max_snapshot_bytes:
        raise ValueError('dbt snapshot payload exceeds budget')
    rows['dbt_projects'].append([workspace, pid, run_id, snapshot.root_path, snapshot.package_name,
        snapshot.fingerprint, json.dumps({**asdict(snapshot.context), 'settings': settings or {}}), json.dumps(result.coverage)])
    rows['dbt_project_snapshots'].append([workspace, run_id, pid, snapshot.fingerprint, payload])

    def support(owner_type, owner_id, refs):
        for ref in refs:
            eid = stable_id(pid, owner_type, owner_id, ref.source.file_id, ref.source.content_hash,
                            str(ref.start_offset), str(ref.end_offset), ref.json_pointer or '')
            rows['dbt_evidence'].append([workspace, eid, pid, run_id, owner_type, owner_id,
                ref.source.file_id, ref.source.content_hash, ref.start_line, ref.end_line,
                ref.start_offset, ref.end_offset, ref.json_pointer, ref.excerpt, ref.origin])
    for r in result.resources:
        aid = stable_id(workspace, 'dbt:' + r.resource_id) if r.resource_type in {'model', 'seed', 'snapshot', 'source'} else None
        rows['dbt_resources'].append([workspace, r.resource_id, pid, run_id, r.unique_id,
            r.resource_type, r.package_name, r.name, r.version, r.enabled, aid, json.dumps(r.metadata)])
        support('resource', r.resource_id, [r.definition])
    for rid, ref in result.generated_evidence:
        support('resource', rid, [ref])
    for relation in result.relationships:
        rid = stable_id(pid, relation.source_id, relation.target_id, relation.kind, relation.status)
        rows['dbt_relationships'].append([workspace, rid, pid, run_id, relation.source_id,
            relation.target_id, relation.kind, relation.status])
        support('relationship', rid, relation.evidence)
    for binding in result.bindings:
        bid = stable_id(pid, binding.resource_id, binding.context_id)
        rows['dbt_relation_bindings'].append([workspace, bid, pid, binding.resource_id,
            binding.context_id, binding.database, binding.schema, binding.identifier,
            json.dumps(binding.quoted), binding.status])
        support('binding', bid, binding.evidence)
    return rows


def load_committed_dbt_results(store, workspace):
    return tuple(DbtProjectResult.from_dict(json.loads(r['payload_json'])) for r in store.rows('''
        SELECT s.payload_json FROM dbt_projects p JOIN dbt_project_snapshots s
        ON p.workspace_id=s.workspace_id AND p.project_id=s.project_id AND p.run_id=s.run_id
        WHERE p.workspace_id=? ORDER BY p.root_path''', [workspace]))


def load_dbt_project_snapshot(store, workspace, run_id, project_id):
    rows = store.rows('SELECT payload_json FROM dbt_project_snapshots WHERE workspace_id=? AND run_id=? AND project_id=?',
                      [workspace, run_id, project_id])
    if not rows:
        raise ValueError('dbt project snapshot is unavailable')
    return DbtProjectResult.from_dict(json.loads(rows[0]['payload_json']))
