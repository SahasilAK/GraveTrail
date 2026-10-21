"""Resolve logical references independently of physical relation names."""
from dataforge.dbt.models import RelationBinding
from dataforge.models import AssetRef


def asset_ref(resource):
    kind = 'view' if resource.metadata.get('config', {}).get('materialized') == 'view' else 'table'
    return AssetRef(resource.name, kind=kind, identity='dbt:' + resource.resource_id)


def resolve_reference(resources, caller, call):
    args = call.args
    package = caller.package_name
    if call.name == 'source' and len(args) == 2 and all(isinstance(a, str) for a in args):
        candidates = [r for r in resources if r.resource_type == 'source' and r.name == '.'.join(args)
                      and r.package_name == package]
    elif call.name == 'ref' and len(args) in {1, 2} and all(isinstance(a, str) for a in args):
        if len(args) == 2:
            package = args[0]
        candidates = [r for r in resources if r.resource_type in {'model', 'seed', 'snapshot'}
                      and r.name == args[-1] and r.package_name == package]
        version = call.kwargs.get('version', call.kwargs.get('v'))
        if version is not None:
            candidates = [r for r in candidates if r.version == str(version)]
        elif len(candidates) > 1:
            candidates = [r for r in candidates if str(r.metadata.get('latest_version')) == r.version]
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
        identifier = resource.metadata.get('identifier', resource.metadata.get('alias', config.get('alias', resource.name)))
        bindings.append(RelationBinding(resource.resource_id, database if isinstance(database, str) else None,
            schema if isinstance(schema, str) else None, str(identifier), (False, False, False),
            snapshot.fingerprint, 'artifact' if resource.unique_id else 'partial', (resource.definition,)))
    return tuple(bindings)
