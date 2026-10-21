"""dbt source context for AI: safe inventory only, never parser lineage answers."""
from __future__ import annotations

from dataclasses import asdict

from dataforge.dbt.artifacts import manifest_resources, read_artifact
from dataforge.dbt.resources import collect_resources
from dataforge.dbt.service import discover_dbt_snapshots, is_dbt
from dataforge.dbt.templates import scan_template


def prepare_dbt_context(store, workspace, inventory, selected):
    files = [m for m in inventory if is_dbt(m)]
    by_id = {m['file_id']: m for m in files}
    text = {fid: store.snapshot_content(m) for fid, m in by_id.items()}
    snapshots = discover_dbt_snapshots(files, lambda ref: text[ref.file_id], store.setting(workspace, 'dbt', {}))
    contexts, closure = {}, set()
    for snapshot in snapshots:
        ids = {s.file_id for s in snapshot.sources}
        if not ids & selected:
            continue
        # Project context is disclosed before dispatch, including context-only files.
        closure.update(ids)
        manifests = [s for s in snapshot.sources if s.file_id in snapshot.context.artifact_file_ids
                     and s.relative_path.rsplit('/', 1)[-1] == 'manifest.json']
        nodes = {}
        if manifests and snapshot.context.mode != 'source':
            document = read_artifact(manifests[0], text[manifests[0].file_id])
            resources, nodes = manifest_resources(document, snapshot)
        else:
            resources, _ = collect_resources(snapshot, lambda ref: text[ref.file_id])
        definitions = {r.resource_id: r for r in resources}
        for ref in snapshot.sources:
            own = [r for r in resources if r.definition.source.file_id == ref.file_id and r.enabled
                   and r.resource_type in {'model', 'snapshot', 'test'}]
            executable = bool(own) and ref.relative_path.endswith(('.sql', '.py', '.json'))
            needed = {r.resource_id for r in own}
            pending = [text[ref.file_id]]
            seen = set()
            while pending and len(seen) < 1000:
                code = pending.pop()
                for call in scan_template(code, variables=snapshot.context.public_vars).calls:
                    if call.name == 'ref':
                        matches = [r for r in resources if r.name == (call.args[-1] if call.args else '')
                                   and (len(call.args) < 2 or r.package_name == call.args[0])]
                    elif call.name == 'source':
                        matches = [r for r in resources if r.name == '.'.join(str(a) for a in call.args)]
                    else:
                        matches = [r for r in resources if r.resource_type == 'macro'
                                   and r.name == call.name.rsplit('.', 1)[-1]]
                    for resource in matches:
                        needed.add(resource.resource_id)
                        if resource.resource_type == 'macro' and resource.resource_id not in seen:
                            seen.add(resource.resource_id)
                            pending.append(text[resource.definition.source.file_id])
            declarations = [asdict(definitions[rid]) for rid in sorted(needed)]
            configs = [{'file_id': s.file_id, 'content_hash': s.content_hash, 'path': s.relative_path,
                        'code': text[s.file_id]} for s in snapshot.sources
                       if s.relative_path.endswith(('.yml', '.yaml'))]
            contexts[ref.file_id] = {'name': 'dbt_project_context', 'unit_id': '',
                'job_id': snapshot.project_id, 'project_id': snapshot.project_id,
                'package': snapshot.package_name, 'root': snapshot.root_path, 'mode': snapshot.context.mode,
                'settings': asdict(snapshot.context), 'resources': declarations, 'configuration_sources': configs,
                'disposition': 'extraction' if executable else 'context_only',
                'origin': 'artifact_declared' if nodes else 'source',
                'unit_ranges': sorted({(r.definition.start_offset, r.definition.end_offset) for r in own}) if nodes else [],
                'context_version': 1}
    return contexts, closure
