"""Reconcile explicit DDL without assuming runtime order or discovering a database schema."""
import json
from collections import defaultdict
from graphlib import CycleError, TopologicalSorter
from typing import Any

from dataforge.asset_identity import AssetResolver
from dataforge.models import AssetRef, Diagnostic, ParseResult, column_key, operation_ids


def sas_stack_columns(record, read_layout):
    """Bind combined SAS columns to the datasets that supply them."""
    columns = defaultdict(list)
    keys = set(record.get("sas_merge_by", ()))
    for item in record["inputs"]:
        names = read_layout(item["table"], item.get("table_identity", ""))
        if not names or any(not name.isidentifier() for name in names):
            return {}
        rename = item.get("sas_rename", {})
        original = {name.casefold() for name in names}
        available = {rename.get(name, name) for name in original}
        if not rename.keys() <= original or not keys <= available or len(available) != len(names):
            return {}
        binding = {key: value for key, value in item.items() if key != "sas_rename"}
        for name in names:
            columns[rename.get(name.casefold(), name.casefold())].append({**binding, "column": name})
    return {} if set(record.get("sas_flags", ())) & columns.keys() else dict(columns)


def query_output_layouts(records, read_layout, case_sensitive):
    """Return complete projection layouts by scope, aligning deferred UNION ALL by width."""
    branches = defaultdict(lambda: defaultdict(list))
    for record in records:
        branches[record.get("scope", "")][record.get("branch", 0)].append(record)
    scoped = {}
    for scope, projections in branches.items():
        alternatives = []
        deferred_union = any("union_projection" in r for branch in projections.values() for r in branch)
        for branch in projections.values():
            names = []
            for record in branch:
                if record.get("sas_stack"):
                    columns = sas_stack_columns(record, read_layout)
                    if not columns:
                        break
                    names.extend(columns)
                    continue
                name = record.get("union_projection", record["target_column"])
                if name not in {"", "*"}:
                    names.append(name)
                    continue
                inputs = [item for item in record["inputs"] if item["role"] == "value"]
                if ((name != "*" and not record.get("sas_passthrough")) or not record.get("wildcard_safe") or len(inputs) != 1
                        or any(record.get(key) for key in ("struct_path", "wildcard_exclude", "wildcard_reserved"))):
                    break
                item = inputs[0]
                expanded = (scoped.get(item["scope"], []) if item.get("scope")
                            else read_layout(item["table"], item.get("table_identity", "")))
                if not expanded:
                    break
                excluded = set(record.get("sas_exclude", ()))
                names.extend(name for name in expanded if name.casefold() not in excluded)
            else:
                alternatives.append(names)
        if len(alternatives) != len(projections):
            continue
        first = alternatives[0]
        if (len({column_key(name, case_sensitive) for name in first}) == len(first)
                and all(len(names) == len(first) and (deferred_union or names == first) for names in alternatives)):
            scoped[scope] = first
    return scoped


def collect_query_layouts(candidates, resolver, schemas):
    """Infer read layouts from single imported query definitions in dependency order."""
    layouts = {}
    order = TopologicalSorter()
    bindings = {}
    for asset, (source, parsed, records) in candidates.items():
        tables = {}
        for record in records:
            if record["category"] != "wildcard" or not record.get("wildcard_safe"):
                continue
            for item in record["inputs"]:
                if item["role"] == "value" and not item.get("scope"):
                    table = item["table"]
                    tables[table] = resolver.resolve(AssetRef(table), source, parsed)[0]
        bindings[asset] = tables
        order.add(asset, *(dependency for dependency in tables.values() if dependency in candidates))
    try:
        order.prepare()
    except CycleError:
        pass  # Acyclic definitions are still available from get_ready().
    while order.is_active():
        for asset in order.get_ready():
            _, _, records = candidates[asset]

            def read_layout(table, identity=""):
                source_asset = bindings[asset].get(table)
                return schemas.get(source_asset, {}).get("column_identifiers") or layouts.get(source_asset, [])

            scoped = query_output_layouts(records, read_layout, resolver.config["case_sensitive"])
            if scoped.get(""):
                layouts[asset] = scoped[""]
            order.done(asset)
    return layouts


def collect_schemas(results: list[tuple[dict[str, Any], ParseResult]], workspace: str, resolver: AssetResolver):
    """Reconcile declared schemas by resolved asset identity and retain their evidence.

    Args:
        results: Source records paired with their parser results.
        workspace: Workspace identifier used to create stable evidence IDs.
        resolver: Resolver that applies the workspace's asset identity rules.

    Returns:
        Declared schemas and separately inferred query layouts by resolved asset ID.
        Conflicting or incomplete declarations do not expose columns for wildcard expansion."""
    normalize, resolve = resolver.norm, resolver.resolve
    records = [(source, parsed, record) for source, parsed in results
               for record in parsed.metadata.get("declared_schemas", [])]
    qualified = {}
    for source, _, record in records:
        name = normalize(record["table"])
        if "." in name:
            qualified.setdefault(name.rsplit(".", 1)[-1], []).append((record["table"], source))
    declarations = {}
    for source, parsed, record in records:
        aid, _ = resolve(AssetRef(record["table"], identity=record.get('asset_identity', '')), source, parsed)
        declarations.setdefault(aid, []).append((source, parsed, record))
        name = normalize(record["table"])
        if "." not in name and not record.get('asset_identity'):
            # Ambiguous unqualified DDL may affect any qualified candidate; never choose one.
            for candidate, declaration_source in qualified.get(name, []):
                if not resolver.visible_from(candidate, declaration_source, source):
                    continue
                possible, _ = resolve(AssetRef(candidate), source, parsed)
                if possible != aid:
                    declarations.setdefault(possible, []).append((source, parsed, {**record, "columns": None}))
    schemas = {}
    query_definitions = {}
    for aid, records in declarations.items():
        name = normalize(records[0][2]["table"])
        signatures = set()
        evidence = []
        valid = True
        for source, parsed, record in records:
            columns = record["columns"]
            valid = valid and bool(columns)
            if columns:
                identifiers = record.get('column_identifiers') or [c['name'] for c in columns]
                names = [column_key(name, resolver.config['case_sensitive']) for name in identifiers]
                valid = valid and len(set(names)) == len(names)
                signatures.add(json.dumps([(name, c['type']) for name, c in zip(names, columns)]))
            index = record.get('operation_index', -1)
            operation = parsed.operations[index] if type(index) is int and 0 <= index < len(parsed.operations) else None
            if operation is None or not any(normalize(ref.name) == normalize(record['table'])
                                             for ref in [*operation.sources, *operation.targets]):
                valid = False
                continue
            if (len(records) == 1 and record.get("query_layout") and resolver.registry[aid][4] != "unresolved"
                    and operation.method in {"parser", "sas-rules", "sas-proc-sql"}):
                projections = (operation.derivations if len(operation.targets) == 1 else [
                    d for d in operation.derivations if d.get("sas_routed")
                    and normalize(d["target_table"]) == normalize(record["table"])])
                if projections:
                    query_definitions[aid] = (source, parsed, projections)
            statement_id, _ = operation_ids(workspace, source, index, operation)
            evidence.append({"file_id": source["file_id"], "relative_path": source["relative_path"],
                "source_hash": source["content_hash"], "start_line": record["start_line"],
                "end_line": record["end_line"], "statement_id": statement_id})
        valid = valid and len(signatures) == 1
        schemas[aid] = {"schema_status": "declared" if valid else "unresolved",
            "columns": records[0][2]["columns"] if valid else [], "schema_evidence": evidence,
            "column_identifiers": (records[0][2].get('column_identifiers') or
                                   [c['name'] for c in records[0][2]['columns']]) if valid else []}
        if not valid and any(record["columns"] for _, _, record in records):
            for _, parsed, record in records:
                message = f"Schema for {name} is conflicting, incomplete or changed; wildcard expansion disabled"
                if not any(d.message == message for d in parsed.diagnostics):
                    parsed.diagnostics.append(Diagnostic(message, record["start_line"], symbol=name))
    layouts = collect_query_layouts(query_definitions, resolver, schemas) if resolver.config["expand_wildcards"] else {}
    return schemas, layouts
