"""Bounded artifact readers with exact JSON locations and explicit schema qualification."""
import json
from dataclasses import dataclass

from dataforge.dbt.evidence import evidence
from dataforge.dbt.models import DbtResource
from dataforge.dbt.resources import resource_id

SCHEMAS = {'manifest': 12, 'catalog': 1, 'run-results': 6}


@dataclass
class ArtifactDocument:
    source: object
    text: str
    data: dict
    spans: dict
    kind: str


def read_artifact(source, text, limits=None):
    decoder = json.JSONDecoder(parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid JSON constant')))
    spans, count = {}, 0

    def whitespace(i):
        while i < len(text) and text[i].isspace():
            i += 1
        return i

    def parse(i, path=()):
        nonlocal count
        count += 1
        if count > 100000 or len(path) > 64:
            raise ValueError('Artifact node or nesting budget exceeded')
        i = whitespace(i)
        start = i
        if i >= len(text):
            raise ValueError('Incomplete JSON')
        if text[i] == '{':
            value, i = {}, whitespace(i + 1)
            if i < len(text) and text[i] != '}':
                while True:
                    key, i = decoder.raw_decode(text, i)
                    if not isinstance(key, str):
                        raise ValueError('JSON object key must be a string')
                    if key in value:
                        raise ValueError('Duplicate artifact JSON key')
                    i = whitespace(i)
                    if i >= len(text) or text[i] != ':':
                        raise ValueError('Invalid JSON object')
                    value[key], i = parse(i + 1, (*path, key))
                    i = whitespace(i)
                    if i >= len(text) or text[i] != ',':
                        break
                    i = whitespace(i + 1)
            if i >= len(text) or text[i] != '}':
                raise ValueError('Invalid JSON object')
            i += 1
        elif text[i] == '[':
            value, i = [], whitespace(i + 1)
            if i < len(text) and text[i] != ']':
                while True:
                    item, i = parse(i, (*path, len(value)))
                    value.append(item)
                    i = whitespace(i)
                    if i >= len(text) or text[i] != ',':
                        break
                    i = whitespace(i + 1)
            if i >= len(text) or text[i] != ']':
                raise ValueError('Invalid JSON array')
            i += 1
        else:
            value, i = decoder.raw_decode(text, i)
        spans[path] = (start, i)
        return value, i

    try:
        data, end = parse(0)
        if whitespace(end) != len(text) or not isinstance(data, dict):
            raise ValueError('Invalid artifact JSON')
    except (RecursionError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid or over-budget artifact JSON') from exc
    schema = data.get('metadata', {}).get('dbt_schema_version', '')
    kind = next((kind for kind, version in SCHEMAS.items()
                 if schema == f'https://schemas.getdbt.com/dbt/{kind}/v{version}.json'), None)
    if kind is None:
        raise ValueError('Unsupported dbt artifact schema; manifest v12/catalog v1/run-results v6 are qualified')
    return ArtifactDocument(source, text, data, spans, kind)


def pointer(path):
    return '/' + '/'.join(str(p).replace('~', '~0').replace('/', '~1') for p in path)


def artifact_evidence(document, path, origin='artifact_declared'):
    start, end = document.spans[path]
    return evidence(document.source, document.text, start, end, pointer=pointer(path), origin=origin)


def manifest_resources(document, snapshot):
    result, nodes = [], {}
    for section in ('nodes', 'sources', 'macros', 'exposures', 'metrics', 'semantic_models', 'saved_queries', 'groups', 'functions'):
        values = document.data.get(section, {})
        if not isinstance(values, dict):
            raise ValueError('Invalid manifest resource section')
        for uid, node in values.items():
            if not isinstance(node, dict) or node.get('unique_id', uid) != uid:
                raise ValueError('Invalid manifest resource identity')
            kind, name = node.get('resource_type', section.removesuffix('s')), node.get('name')
            package = node.get('package_name')
            if not isinstance(name, str) or not isinstance(package, str):
                raise ValueError('Manifest resource name/package are required')
            if kind == 'source':
                name = node.get('source_name', '') + '.' + name
            metadata = {key: node[key] for key in ('description', 'columns', 'config', 'database', 'schema',
                'alias', 'identifier', 'version', 'latest_version', 'language', 'tags', 'group', 'access') if key in node}
            metadata['relative_path'] = node.get('original_file_path', '')
            metadata['evidence_origin'] = 'artifact_declared'
            rid = resource_id(snapshot, kind, name, node.get('version'), package)
            resource = DbtResource(rid, uid, snapshot.project_id, package, kind, name,
                None if node.get('version') is None else str(node['version']),
                node.get('config', {}).get('enabled', True) is not False,
                artifact_evidence(document, (section, uid)), metadata)
            result.append(resource)
            nodes[uid] = (resource, node, section)
    return tuple(result), nodes


def bind_artifacts(documents):
    manifests = [d for d in documents if d.kind == 'manifest']
    if len(manifests) != 1:
        raise ValueError('Choose one manifest for an artifact context')
    manifest = manifests[0].data
    metadata = manifest['metadata']
    resources = {**manifest.get('nodes', {}), **manifest.get('sources', {})}
    observations = {}
    for document in documents:
        if document.kind == 'manifest':
            continue
        docmeta = document.data.get('metadata', {})
        if docmeta.get('project_name') and docmeta['project_name'] != metadata.get('project_name'):
            raise ValueError('Artifact project mismatch')
        if document.kind == 'run-results':
            if not metadata.get('invocation_id') or docmeta.get('invocation_id') != metadata['invocation_id']:
                raise ValueError('Artifact invocation mismatch')
            for result in document.data.get('results', []):
                uid = result.get('unique_id')
                if uid not in resources:
                    raise ValueError('Run result belongs to another artifact context')
                observations.setdefault(uid, {})['observed_run'] = {key: result[key] for key in
                    ('status', 'execution_time', 'failures') if key in result}
        elif document.kind == 'catalog':
            for uid, result in {**document.data.get('nodes', {}), **document.data.get('sources', {})}.items():
                if uid not in resources:
                    raise ValueError('Catalog belongs to another artifact context')
                node, physical = resources[uid], result.get('metadata', {})
                expected = (node.get('database'), node.get('schema'), node.get('identifier', node.get('alias', node.get('name'))))
                actual = (physical.get('database'), physical.get('schema'), physical.get('name'))
                if expected != actual:
                    raise ValueError('Catalog physical relation context mismatch')
                observations.setdefault(uid, {}).update({'observed_columns': result.get('columns', {}),
                    'catalog_generated_at': docmeta.get('generated_at'),
                    'catalog_errors': bool(document.data.get('errors'))})
    return observations
