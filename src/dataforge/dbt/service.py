"""Shared project preparation and resource queries for all adapters."""
import json
from collections import deque

from dataforge.dbt.analysis import analyze_dbt_project
from dataforge.dbt.discovery import discover_projects, source_refs
from dataforge.dbt.models import DbtSettings
from dataforge.dbt.persistence import load_committed_dbt_results

READS = {'dbt_projects', 'dbt_resources', 'dbt_resource', 'dbt_dependencies'}


class DbtOperations:
    """Thin shared agent handlers; AgentService owns authorization and response budgets."""

    def _dbt_projects(self, w, opts):
        from dataforge.agent.paging import page
        rows = self.store.rows('''SELECT project_id,root_path,package_name,run_id,fingerprint,
            coverage_json FROM dbt_projects WHERE workspace_id=? ORDER BY root_path''', [w])
        for row in rows:
            row['coverage'] = json.loads(row.pop('coverage_json'))
        return page(rows, opts, ['dbt_projects', w, [r['fingerprint'] for r in rows]])

    def _dbt_resources(self, w, opts, project_id='', resource_types=None):
        from dataforge.agent.paging import page
        rows = self.store.rows('''SELECT resource_id,project_id,resource_type,package_name,name,
            version,enabled,asset_id,run_id FROM dbt_resources WHERE workspace_id=?
            AND (?='' OR project_id=?) ORDER BY resource_type,name,version,resource_id LIMIT 100001''',
            [w, project_id, project_id])
        if len(rows) > 100000:
            raise ValueError('Narrow the dbt resource query to one project')
        if resource_types:
            rows = [r for r in rows if r['resource_type'] in resource_types]
        return page(rows, opts, ['dbt_resources', w, project_id, resource_types, [r['run_id'] for r in rows]])

    def _dbt_resource(self, w, opts, resource_id):
        rows = self.store.rows('SELECT * FROM dbt_resources WHERE workspace_id=? AND resource_id=?', [w, resource_id])
        if not rows:
            raise ValueError('Resource does not belong to this workspace')
        resource = rows[0]
        metadata = json.loads(resource.pop('metadata_json'))
        if opts.detail_level == 'detailed':
            resource['metadata'] = metadata
            resource['evidence'] = self.store.rows('''SELECT file_id,content_hash,start_line,end_line,
                json_pointer,excerpt,origin FROM dbt_evidence WHERE workspace_id=?
                AND owner_type='resource' AND owner_id=? ORDER BY evidence_id''', [w, resource_id])
        else:
            resource['coverage'] = metadata.get('column_coverage', 'See project coverage')
        return resource

    def _dbt_dependencies(self, w, opts, resource_id, direction='downstream', relationship_kinds=None, max_depth=10):
        from dataforge.agent.paging import page
        if direction not in {'upstream', 'downstream'} or type(max_depth) is not int or not 1 <= max_depth <= 30:
            raise ValueError('Use upstream/downstream and depth 1–30')
        resource = self._dbt_resource(w, opts.model_copy(update={'detail_level': 'summary'}), resource_id)
        rows = self.store.rows('''SELECT * FROM dbt_relationships WHERE workspace_id=? AND project_id=?
            AND status='resolved' ORDER BY relationship_id LIMIT 100001''', [w, resource['project_id']])
        if len(rows) > 100000:
            raise ValueError('dbt relationship budget exceeded')
        links = {}
        for relation in rows:
            if relationship_kinds and relation['kind'] not in relationship_kinds:
                continue
            source, target = (relation['source_id'], relation['target_id']) if direction == 'downstream' else (
                relation['target_id'], relation['source_id'])
            links.setdefault(source, []).append((target, relation))
        queue, seen, output = deque([(resource_id, 0)]), {resource_id}, []
        boundary = False
        while queue:
            current, depth = queue.popleft()
            if depth == max_depth:
                boundary |= bool(links.get(current))
                continue
            for target, relation in links.get(current, []):
                cycle = target in seen
                output.append({**relation, 'depth': depth + 1, 'cycle_or_repeated': cycle})
                if not cycle:
                    seen.add(target)
                    queue.append((target, depth + 1))
        return page(output, opts, ['dbt_dependencies', w, resource['run_id'], resource_id,
            direction, max_depth, relationship_kinds], depth_boundary=boundary)


def is_dbt(metadata):
    return json.loads(metadata.get('metadata') or '{}').get('source_kind') == 'dbt'


def prepare_ai_dbt_inventory(prepared, results):
    """Safe resource inventory and AI-derived data relationships; no static lineage."""
    from dataforge.dbt.evidence import evidence
    from dataforge.dbt.models import DbtProjectResult, DbtRelationship
    from dataforge.dbt.resources import collect_resources
    sources = {s.file_id: s for s in prepared.sources if s.source_kind == 'dbt'}
    if not sources:
        return []
    files = [m for m, _ in results if m['file_id'] in sources]
    snapshots = discover_dbt_snapshots(files, lambda ref: sources[ref.file_id].code,
                                      prepared.settings.get('dbt', {}))
    projects = []
    for snapshot in snapshots:
        resources, diagnostics = collect_resources(snapshot, lambda ref: sources[ref.file_id].code)
        manifests = [s for s in snapshot.sources if s.relative_path.rsplit('/', 1)[-1] == 'manifest.json']
        if manifests and snapshot.context.mode != 'source':
            from dataforge.dbt.artifacts import manifest_resources, read_artifact
            resources, _ = manifest_resources(read_artifact(manifests[0], sources[manifests[0].file_id].code), snapshot)
        ids = {r.resource_id for r in resources}
        selected = tuple((m, p) for m, p in results if m['file_id'] in {s.file_id for s in snapshot.sources})
        relationships = []
        for metadata, parsed in selected:
            text = sources[metadata['file_id']].code
            for operation in parsed.operations:
                ref = evidence(metadata, text, origin='ai_inferred')
                for source in operation.sources:
                    for target in operation.targets:
                        a, b = source.identity.removeprefix('dbt:'), target.identity.removeprefix('dbt:')
                        if a in ids and b in ids:
                            relationships.append(DbtRelationship(a, b, 'data_read', 'resolved', (ref,)))
        projects.append(DbtProjectResult(snapshot, tuple(resources), tuple(relationships), file_results=selected,
            coverage={'ai_mode': 'ai', 'columns': 'inferred', 'semantic_completeness': 'not_proven'}))
    return projects


def discover_dbt_snapshots(files, read_source, stored_settings):
    by_id = {m['file_id']: m for m in files}
    settings = DbtSettings.model_validate(stored_settings)
    snapshots = discover_projects(source_refs(files), read_source, settings=settings)
    if 'mode' not in stored_settings:
        from dataclasses import replace

        from dataforge.models import stable_id
        adjusted = []
        for snapshot in snapshots:
            mode = stored_settings.get('projects', {}).get(snapshot.root_path, {}).get('mode', next((
                json.loads(by_id[ref.file_id]['metadata']).get('dbt_mode', 'source') for ref in snapshot.sources), 'source'))
            adjusted.append(replace(snapshot, context=replace(snapshot.context, mode=mode),
                                    fingerprint=stable_id(snapshot.fingerprint, mode)))
        snapshots = tuple(adjusted)
    return snapshots


def prepare_dbt_analysis(store, workspace, file_ids=None, force=False, cancelled=None):
    from dataforge.services import PARSER_VERSION

    files = [m for m in store.files(workspace) if is_dbt(m)]
    by_id = {m['file_id']: m for m in files}
    stored_settings = store.setting(workspace, 'dbt', {})
    snapshots = discover_dbt_snapshots(files, lambda ref: store.snapshot_content(by_id[ref.file_id]), stored_settings)
    previous = {r.snapshot.project_id: r for r in load_committed_dbt_results(store, workspace)}
    publication = store.rows('SELECT parser_version FROM column_analysis WHERE workspace_id=?', [workspace])
    current_parser = bool(publication) and publication[0]['parser_version'] == PARSER_VERSION
    projects, analyzed, cached = [], 0, 0
    for snapshot in snapshots:
        if cancelled and cancelled():
            raise InterruptedError('dbt analysis cancelled; previous lineage retained')
        selected = file_ids is None or bool(set(file_ids) & {s.file_id for s in snapshot.sources})
        old = previous.get(snapshot.project_id)
        if (old and current_parser and not old.coverage.get('ai_mode')
                and old.snapshot.fingerprint == snapshot.fingerprint and not (force and selected)):
            result = old
            cached += len(snapshot.sources)
        elif selected or old:
            result = analyze_dbt_project(snapshot, lambda ref: store.snapshot_content(by_id[ref.file_id]))
            analyzed += len(snapshot.sources)
        else:
            continue
        refreshed = []
        for metadata, parsed in result.file_results:
            current = by_id[metadata['file_id']]
            parsed.metadata = {**json.loads(current['metadata']), **parsed.metadata}
            refreshed.append((current, parsed))
        from dataclasses import replace
        projects.append(replace(result, file_results=tuple(refreshed)))
    if files and not snapshots:
        raise ValueError('dbt project configuration is missing; previous lineage retained')
    return projects, {'analyzed': analyzed, 'cached': cached}


def dbt_settings_current(store, workspace):
    settings = DbtSettings.model_validate(store.setting(workspace, 'dbt', {})).model_dump()
    return all(json.loads(row['context_json']).get('settings') == settings
               for row in store.rows('SELECT context_json FROM dbt_projects WHERE workspace_id=?', [workspace]))
