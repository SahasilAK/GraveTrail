"""Source resource inventory, including non-SQL dbt resources."""
import ast
import csv
import io
from dataclasses import replace
from pathlib import PurePosixPath

from dataforge.dbt.evidence import evidence
from dataforge.dbt.models import DbtResource
from dataforge.dbt.templates import scan_template
from dataforge.dbt.yaml import read_project_paths, read_yaml, within
from dataforge.models import stable_id

DATA_TYPES = {'model', 'source', 'seed', 'snapshot'}
YAML_RESOURCES = {'models': 'model', 'snapshots': 'snapshot', 'seeds': 'seed', 'macros': 'macro',
    'exposures': 'exposure', 'metrics': 'metric', 'semantic_models': 'semantic_model',
    'saved_queries': 'saved_query', 'groups': 'group', 'unit_tests': 'unit_test',
    'functions': 'function', 'data_tests': 'test'}


def resource_id(snapshot, kind, name, version=None, package=None):
    return stable_id(snapshot.project_id, package or snapshot.package_name, kind, name,
                     '' if version is None else str(version))


def scan_python_model(text, source=None, limits=None):
    calls, config = [], {}
    try:
        tree = ast.parse(text)
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        if sum(1 for _ in ast.walk(tree)) > 100000:
            raise ValueError('Python AST node budget exceeded')
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if not isinstance(node.func.value, ast.Name) or node.func.value.id != 'dbt':
                continue
            try:
                args = tuple(ast.literal_eval(a) for a in node.args)
                kwargs = {k.arg: ast.literal_eval(k.value) for k in node.keywords}
            except (ValueError, TypeError):
                continue
            if node.func.attr in {'ref', 'source'}:
                ancestors, current = [], node
                while current in parents:
                    current = parents[current]
                    ancestors.append(current)
                owner = next((n for n in ancestors if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))), None)
                conditional = any(isinstance(n, (ast.If, ast.IfExp, ast.For, ast.While, ast.Try,
                    ast.comprehension, ast.ListComp, ast.DictComp, ast.GeneratorExp, ast.Lambda)) for n in ancestors)
                unshadowed = owner is not None and owner.name == 'model' and 'dbt' in [a.arg for a in owner.args.args]
                if owner and any(isinstance(n, ast.Name) and n.id == 'dbt' and isinstance(n.ctx, ast.Store) for n in ast.walk(owner)):
                    unshadowed = False
                calls.append((node.func.attr, args, kwargs, node.lineno, conditional or not unshadowed))
            elif node.func.attr == 'config':
                config.update(kwargs)
    except (SyntaxError, RecursionError, MemoryError) as exc:
        raise ValueError('Unsupported or over-budget Python model') from exc
    return calls, config


def collect_resources(snapshot, read_source):
    resources, declarations, diagnostics = {}, [], []
    sources = {s.relative_path: s for s in snapshot.sources}
    config_path = str(PurePosixPath(snapshot.root_path) / 'dbt_project.yml')
    project_config = read_yaml(read_source(sources[config_path]))[0] if config_path in sources else {}
    paths = read_project_paths(read_source(sources[config_path])) if config_path in sources else {}
    package_directory = str(PurePosixPath(snapshot.root_path) / paths.get('packages-install-path', ('dbt_packages',))[0])
    package_configs = [s for s in snapshot.sources if s.relative_path.endswith('/dbt_project.yml')
                       and within(s.relative_path, package_directory)]

    def add(kind, name, source, text, *, metadata=None, version=None, start=0, end=None):
        rid = resource_id(snapshot, kind, name, version)
        if rid in resources:
            raise ValueError(f'Duplicate dbt resource: {kind}.{name}')
        meta = {'relative_path': source.relative_path, 'dbt_root': snapshot.root_path, **(metadata or {})}
        resources[rid] = DbtResource(rid, None, snapshot.project_id, snapshot.package_name,
            kind, name, None if version is None else str(version), meta.get('config', {}).get('enabled', True) is not False,
            evidence(source, text, start, end), meta)
        return resources[rid]

    def add_tests(name, item, source, text, source_args=None):
        for column, declaration in [(None, item), *[(c.get('name'), c) for c in item.get('columns', [])]]:
            for index, test in enumerate(declaration.get('data_tests', declaration.get('tests', [])) or []):
                test_name = test if isinstance(test, str) else next(iter(test))
                add('test', f'{name}.{column or "model"}.{test_name}.{index}', source, text,
                    metadata={'model': name, 'column': column, 'test': test,
                              **({'source_args': source_args} if source_args else {})})

    for source in snapshot.sources:
        if any(within(source.relative_path, str(PurePosixPath(c.relative_path).parent)) for c in package_configs):
            continue
        text, suffix = read_source(source), PurePosixPath(source.relative_path).suffix.lower()
        relative = str(PurePosixPath(source.relative_path).relative_to(snapshot.root_path))
        role = next((key.removesuffix('-paths') for key, folders in paths.items()
                     if key.endswith('-paths') and any(within(relative, d) for d in folders)), '')
        if suffix in {'.yml', '.yaml'}:
            data, marks = read_yaml(text)
            declarations.append((source, text, data, marks))
        elif suffix == '.sql':
            facts = scan_template(text, variables=snapshot.context.public_vars)
            if role == 'macro':
                for definition in facts.definitions:
                    add('macro', definition.name, source, text, start=definition.start, end=definition.end,
                        metadata={'block_type': definition.kind})
            elif role == 'snapshot':
                for definition in facts.definitions:
                    if definition.kind == 'snapshot':
                        add('snapshot', definition.name, source, text, start=definition.start, end=definition.end,
                            metadata={'config': facts.config})
            elif role in {'model', 'analysis', 'test'}:
                name = PurePosixPath(relative).stem
                config = inherited_config(project_config, snapshot.package_name, relative, role, paths)
                config.update(facts.config)
                add('model' if role == 'model' else role, name, source, text,
                    metadata={'config': config, 'language': 'sql'})
        elif suffix == '.py' and role == 'model':
            _, inline = scan_python_model(text, source)
            config = {**inherited_config(project_config, snapshot.package_name, relative, role, paths), **inline}
            add('model', PurePosixPath(relative).stem, source, text,
                metadata={'config': config, 'language': 'python', 'column_coverage': 'unsupported_python'})
        elif suffix == '.csv' and role == 'seed':
            header = next(csv.reader(io.StringIO(text)), [])
            add('seed', PurePosixPath(relative).stem, source, text,
                metadata={'columns': [{'name': name} for name in header], 'schema_origin': 'seed_header'})
        elif suffix == '.md':
            for definition in scan_template(text).definitions:
                add('doc', definition.name, source, text, start=definition.start, end=definition.end)
    seen_declarations = set()
    for source, text, data, marks in declarations:
        for item in data.get('sources', []) or []:
            for table in item.get('tables', []) or []:
                name = item['name'] + '.' + table['name']
                add('source', name, source, text, metadata={**item, **table,
                    'source_name': item['name'], 'identifier': table.get('identifier', table['name']),
                    'config': {**item.get('config', {}), **table.get('config', {})}})
                add_tests(name, table, source, text, [item['name'], table['name']])
        for key, kind in YAML_RESOURCES.items():
            for item in data.get(key, []) or []:
                if not isinstance(item, dict) or not isinstance(item.get('name'), str):
                    diagnostics.append(f'Unsupported {key} declaration')
                    continue
                name = item['name']
                declaration_key = (kind, name)
                if declaration_key in seen_declarations:
                    raise ValueError(f'Duplicate dbt property declaration: {kind}.{name}')
                seen_declarations.add(declaration_key)
                if kind in {'model', 'seed', 'macro'}:
                    for version in item.get('versions') or [{}]:
                        v = version.get('v')
                        defined = version.get('defined_in', name if v is None else f'{name}_v{v}')
                        matches = [r for r in resources.values() if r.resource_type == kind and r.name == defined]
                        if len(matches) != 1:
                            diagnostics.append(f'Missing or ambiguous declaration target: {kind}.{defined}')
                            continue
                        old = matches[0]
                        meta = {**old.metadata, **item, **version}
                        meta['config'] = {**old.metadata.get('config', {}), **item.get('config', {}),
                                          **version.get('config', {})}
                        # Inline config takes precedence over YAML for model SQL.
                        if old.metadata.get('language') == 'sql':
                            meta['config'].update(scan_template(read_source(old.definition.source)).config)
                        rid = resource_id(snapshot, kind, name, v)
                        del resources[old.resource_id]
                        resources[rid] = replace(old, resource_id=rid, name=name,
                            version=None if v is None else str(v), metadata=meta,
                            enabled=meta['config'].get('enabled', True) is not False)
                else:
                    add(kind, name, source, text, metadata=item)
                if kind in {'model', 'source', 'seed', 'snapshot'}:
                    add_tests(name, item, source, text)
        # Config/package/selector declarations remain visible without fetching anything.
        for key in ('packages', 'projects', 'selectors'):
            for index, item in enumerate(data.get(key, []) or []):
                add('selector' if key == 'selectors' else 'package', str(item.get('name', item.get('package', index))),
                    source, text, metadata=item)
    for config_source in package_configs:
        root = str(PurePosixPath(config_source.relative_path).parent)
        package = read_yaml(read_source(config_source))[0]['name']
        nested = replace(snapshot, root_path=root, package_name=package,
                         sources=tuple(s for s in snapshot.sources if within(s.relative_path, root)))
        included, warnings = collect_resources(nested, read_source)
        for resource in included:
            if resource.resource_id in resources:
                raise ValueError('Duplicate installed package resource')
            resources[resource.resource_id] = resource
        diagnostics.extend(warnings)
    return tuple(resources.values()), diagnostics


def inherited_config(project_config, package, relative, role, paths=None):
    result = {}
    tree = project_config.get(role + 's', {})
    roots = (paths or {}).get(role + '-paths', (role + 's',))
    root = max((folder for folder in roots if within(relative, folder)), key=len, default=role + 's')
    hierarchy = PurePosixPath(relative).relative_to(root)
    for part in [None, package, *hierarchy.parts[:-1], hierarchy.stem]:
        if part is not None:
            tree = tree.get(part, {}) if isinstance(tree, dict) else {}
        if not isinstance(tree, dict):
            continue
        for key, value in tree.items():
            if key.startswith('+'):
                result[key[1:]] = value
    return result
