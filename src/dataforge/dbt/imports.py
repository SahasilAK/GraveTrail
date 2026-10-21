"""Two-pass project admission over existing guarded importer readers."""
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from dataforge.dbt.yaml import read_project_paths, within
from dataforge.ingestion import safe_relative

ARTIFACTS = {'manifest.json', 'catalog.json', 'run_results.json', 'sources.json',
             'freshness.json', 'semantic_manifest.json', 'osi_document.json'}
EXCLUDED = {'.git', '.venv', 'venv', 'logs', '__pycache__', 'node_modules'}


@dataclass(frozen=True)
class DbtImportOptions:
    mode: str = 'source'
    artifact_paths: tuple[str, ...] = ()
    include_packages: bool = False

    def __post_init__(self):
        if self.mode not in {'source', 'enriched', 'artifact'}:
            raise ValueError('Unknown dbt analysis mode')
        for path in self.artifact_paths:
            safe_relative(path)


@dataclass
class DbtImportPlan:
    paths: dict[str, dict] = field(default_factory=dict)
    roots: dict[str, dict] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)


def excluded(path):
    parts = PurePosixPath(path).parts
    return any(p.casefold() in EXCLUDED or p.startswith('.') for p in parts) or (
        PurePosixPath(path).name.casefold() in {'profiles.yml', 'profiles.yaml', 'secrets.toml'})


def preview_dbt_import(entries, options: DbtImportOptions, read_config) -> DbtImportPlan:
    plan, seen, paths = DbtImportPlan(), set(), []
    for name in entries:
        try:
            path = safe_relative(name)
        except ValueError:
            plan.diagnostics.append('Unsafe relative path excluded')
            continue
        if path.casefold() in seen:
            raise ValueError('dbt import path collision')
        seen.add(path.casefold())
        if not excluded(path):
            paths.append(path)
    for path in sorted(paths, key=lambda p: (len(PurePosixPath(p).parts), p)):
        if PurePosixPath(path).name == 'dbt_project.yml':
            if not options.include_packages and 'dbt_packages' in PurePosixPath(path).parts:
                continue
            root = str(PurePosixPath(path).parent)
            if not options.include_packages and any(within(path, str(PurePosixPath(parent) / conf['packages-install-path'][0]))
                for parent, conf in plan.roots.items()):
                continue
            text = read_config(path)
            resource_paths = read_project_paths(text)
            plan.roots[root] = resource_paths
            plan.paths[path] = {'source_kind': 'dbt', 'dbt_root': root, 'dbt_role': 'project'}
    for path in paths:
        if path in options.artifact_paths:
            if PurePosixPath(path).name not in ARTIFACTS and '/compiled/' not in path:
                raise ValueError('Select a recognized artifact or compiled SQL file')
            if path.endswith('.sql') and not plan.roots:
                raise ValueError('Compiled SQL requires a project/resource binding')
            root = next((r for r in sorted(plan.roots, key=len, reverse=True) if within(path, r)), '.')
            plan.paths[path] = {'source_kind': 'dbt', 'dbt_root': root, 'dbt_role': 'artifact'}
            continue
        root = next((r for r in sorted(plan.roots, key=len, reverse=True) if within(path, r)), None)
        if root is None or path in plan.paths:
            continue
        relative = str(PurePosixPath(path).relative_to(root))
        config = plan.roots[root]
        if within(relative, config['target-path'][0]):
            continue
        if within(relative, config['packages-install-path'][0]) and not options.include_packages:
            continue
        role = None
        name, suffix = PurePosixPath(relative).name, PurePosixPath(relative).suffix.lower()
        if name in {'packages.yml', 'packages.yaml', 'package-lock.yml', 'dependencies.yml', 'selectors.yml'}:
            role = 'config'
        for key, dirs in config.items():
            if not key.endswith('-paths') or not any(within(relative, folder) for folder in dirs):
                continue
            allowed = {'.yml', '.yaml', '.sql', '.md'}
            if key == 'model-paths':
                allowed.add('.py')
            if key in {'seed-paths', 'test-paths'}:
                allowed.add('.csv')
            if suffix in allowed:
                role = key.removesuffix('-paths')
                break
        if role:
            plan.paths[path] = {'source_kind': 'dbt', 'dbt_root': root, 'dbt_role': role}
    if not plan.roots and not (options.mode == 'artifact' and options.artifact_paths):
        raise ValueError('No dbt_project.yml or selected standalone manifest')
    for metadata in plan.paths.values():
        metadata['dbt_mode'] = options.mode
    return plan
