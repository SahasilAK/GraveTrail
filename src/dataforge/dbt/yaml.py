"""Bounded, location-preserving safe YAML and literal dbt resource paths."""
from pathlib import PurePosixPath

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

PATH_DEFAULTS = {'model-paths': ('models',), 'macro-paths': ('macros',),
                 'seed-paths': ('seeds',), 'snapshot-paths': ('snapshots',),
                 'test-paths': ('tests',), 'analysis-paths': ('analyses',), 'docs-paths': ('docs',)}
SAFE_TAGS = {'str', 'null', 'bool', 'int', 'float', 'timestamp', 'seq', 'map'}


def read_yaml(text: str) -> tuple[dict, dict[tuple, tuple[int, int]]]:
    """Construct only safe JSON-like YAML after bounded node/alias validation."""
    marks, count = {}, 0

    def convert(node, path=(), ancestors=frozenset()):
        nonlocal count
        count += 1
        if count > 100000 or len(path) > 64 or id(node) in ancestors:
            raise ValueError('YAML nesting, alias or node budget exceeded')
        if node.tag.removeprefix('tag:yaml.org,2002:') not in SAFE_TAGS:
            raise ValueError(f'Unsupported YAML tag at line {node.start_mark.line + 1}')
        marks[path] = (node.start_mark.index, node.end_mark.index)
        stack = ancestors | {id(node)}
        if isinstance(node, MappingNode):
            result = {}
            for key, value in node.value:
                if not isinstance(key, ScalarNode) or key.tag != 'tag:yaml.org,2002:str':
                    raise ValueError('YAML mapping keys must be strings')
                if key.value in result:
                    raise ValueError(f'Duplicate YAML key at line {key.start_mark.line + 1}')
                result[key.value] = convert(value, (*path, key.value), stack)
            return result
        if isinstance(node, SequenceNode):
            return [convert(value, (*path, i), stack) for i, value in enumerate(node.value)]
        if node.tag.endswith(':timestamp'):
            return node.value
        loader = yaml.SafeLoader('')
        try:
            return loader.construct_object(node)
        finally:
            loader.dispose()

    try:
        # Token budget also bounds parser work before constructing an object graph.
        if sum(1 for _ in yaml.scan(text)) > 100000:
            raise ValueError('YAML token budget exceeded')
        docs = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
        result = {}
        for node in docs:
            if node is None:
                continue
            value = convert(node)
            if not isinstance(value, dict):
                raise ValueError('dbt YAML must contain a mapping')
            for key, item in value.items():
                if key in result and not isinstance(item, list):
                    raise ValueError('Conflicting YAML documents')
                result[key] = result.get(key, []) + item if isinstance(item, list) else item
        return result, marks
    except (yaml.YAMLError, RecursionError, OverflowError) as exc:
        raise ValueError('Invalid or over-budget YAML') from exc


def safe_resource_path(value: str) -> str:
    """Reject dynamic and escaping project paths before filesystem reads."""
    from dataforge.ingestion import safe_relative
    if not isinstance(value, str) or any(s in value for s in ('{{', '{%', '\\')):
        raise ValueError('Resource paths must be literal relative paths')
    return safe_relative(value.rstrip('/')) if value not in ('', '.') else '.'


def read_project_paths(text: str) -> dict[str, tuple[str, ...]]:
    data, _ = read_yaml(text)
    if not isinstance(data.get('name'), str) or not data['name'].strip():
        raise ValueError('dbt project requires a literal name')
    paths = {}
    for key, default in PATH_DEFAULTS.items():
        values = data.get(key, default)
        if not isinstance(values, (list, tuple)):
            raise ValueError('Resource paths must be lists')
        paths[key] = tuple(safe_resource_path(value) for value in values)
    for key, default in [('packages-install-path', 'dbt_packages'), ('target-path', 'target')]:
        paths[key] = (safe_resource_path(data.get(key, default)),)
    return paths


def within(path: str, directory: str) -> bool:
    return directory == '.' or PurePosixPath(path).is_relative_to(PurePosixPath(directory))
