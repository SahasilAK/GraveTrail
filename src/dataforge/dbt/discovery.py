"""Immutable root membership and deterministic project freshness."""
import json
from dataclasses import asdict
from pathlib import PurePosixPath

from dataforge.dbt.models import DbtContext, DbtSettings, ProjectSnapshot, SourceRef
from dataforge.dbt.yaml import read_project_paths, read_yaml, within
from dataforge.models import stable_id


def discover_projects(sources, read_source, options=None, settings=None):
    settings = settings or DbtSettings()
    roots = {}
    for source in sources:
        if PurePosixPath(source.relative_path).name == 'dbt_project.yml':
            text = read_source(source)
            read_project_paths(text)
            config, _ = read_yaml(text)
            roots[str(PurePosixPath(source.relative_path).parent)] = (source, config['name'])
    if not roots:
        for source in sources:
            if PurePosixPath(source.relative_path).name == 'manifest.json' and (
                    not settings.artifact_paths or source.relative_path in settings.artifact_paths):
                artifact = json.loads(read_source(source))
                roots[str(PurePosixPath(source.relative_path).parent)] = (
                    source, artifact.get('metadata', {}).get('project_name', 'artifact'))
    package_roots = set()
    for root, (source, _) in roots.items():
        if not source.relative_path.endswith('dbt_project.yml'):
            continue
        package_path = read_project_paths(read_source(source))['packages-install-path'][0]
        package_directory = str(PurePosixPath(root) / package_path)
        package_roots.update(other for other in roots if other != root and within(other, package_directory))
    roots = {root: value for root, value in roots.items() if root not in package_roots}
    snapshots = []
    for root, (project_file, name) in roots.items():
        project_settings = DbtSettings.model_validate({**settings.model_dump(exclude={'projects'}),
                                                       **settings.projects.get(root, {})})
        members = tuple(s for s in sources if within(s.relative_path, root) and not any(
            other != root and len(other) > len(root) and within(s.relative_path, other) for other in roots))
        project_data = read_yaml(read_source(project_file))[0] if project_file.relative_path.endswith('dbt_project.yml') else {}
        context = DbtContext(project_settings.mode, tuple(s.file_id for s in members
            if s.relative_path in project_settings.artifact_paths or (not project_settings.artifact_paths and
                PurePosixPath(s.relative_path).name in {'manifest.json', 'catalog.json', 'run_results.json'})),
            project_settings.dialect, project_settings.target_label,
            {**project_data.get('vars', {}), **project_settings.public_vars})
        fingerprint = stable_id('dbt-reader-1', json.dumps(sorted((s.relative_path, s.content_hash) for s in members)),
                                json.dumps(asdict(context), sort_keys=True))
        snapshots.append(ProjectSnapshot(stable_id('dbt-project', project_file.file_id, root), root, name,
                                         members, fingerprint, context))
    return tuple(snapshots)


def source_refs(metadata):
    return tuple(SourceRef(m['file_id'], m['content_hash'], m['relative_path']) for m in metadata)
