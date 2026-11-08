"""Resolve logical references independently of physical relation names."""
from dataforge.dbt.models import RelationBinding
from dataforge.models import AssetRef


def asset_ref(resource):
    kind = 'view' if resource.metadata.get('config', {}).get('materialized') == 'view' else 'table'
    return AssetRef(resource.name, kind=kind, identity='dbt:' + resource.resource_id)


def relation_identifier(resource):
    metadata = resource.metadata
    alias = metadata.get('identifier') or metadata.get('alias') or metadata.get('config', {}).get('alias')
    if isinstance(alias, str) and alias.strip():
        return alias.strip()
    if resource.version is not None:
        return f"{resource.name}_v{resource.version.replace('.', '_')}"
    return resource.name


def resolve_reference(resources, caller, call):
    args = call.args
    package = caller.package_name
    if call.name == 'source' and len(args) == 2 and all(isinstance(a, str) for a in args) and not call.kwargs:
        candidates = [r for r in resources if r.resource_type == 'source' and r.name == '.'.join(args)
                      and r.package_name == package]
    elif call.name == 'ref' and len(args) in {1, 2} and all(isinstance(a, str) for a in args):
        if len(call.kwargs) > 1 or call.kwargs.keys() - {'v', 'version'}:
            return None
        if len(args) == 2:
            package = args[0]
        candidates = [r for r in resources if r.resource_type in {'model', 'seed', 'snapshot'}
                      and r.name == args[-1] and r.package_name == package]
        version = call.kwargs.get('version', call.kwargs.get('v'))
        if call.kwargs and type(version) not in {str, int, float}:
            return None
        if version is not None:
            candidates = [r for r in candidates if r.version == str(version)]
        elif len(candidates) > 1:
            declared = {str(r.metadata['latest_version']) for r in candidates
                        if r.metadata.get('latest_version') is not None}
            if declared:
                candidates = [r for r in candidates if r.version in declared] if len(declared) == 1 else []
            else:
                versions = [r.metadata.get('v') for r in candidates]
                comparable = (all(type(v) in {int, float} for v in versions) or
                              all(isinstance(v, str) for v in versions))
                latest = max(versions) if comparable else None
                candidates = [r for r, v in zip(candidates, versions) if v == latest] if comparable else []
    else:
        return None
    active = [r for r in candidates if r.enabled]
    return active[0] if len(active) == 1 else None


def resolve_bindings(resources, snapshot):
    bindings = []
    for resource in resources:
        if resource.resource_type not in {'model', 'seed', 'snapshot', 'source'}:
            continue
        config = resource.metadata.get('config', {})
        if config.get('materialized') == 'ephemeral':
            continue
        database = resource.metadata.get('database', config.get('database'))
        schema = resource.metadata.get('schema', config.get('schema'))
        identifier = relation_identifier(resource)
        bindings.append(RelationBinding(resource.resource_id, database if isinstance(database, str) else None,
            schema if isinstance(schema, str) else None, str(identifier), (False, False, False),
            snapshot.fingerprint, 'artifact' if resource.unique_id else 'partial', (resource.definition,)))
    return tuple(bindings)
