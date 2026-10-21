"""Reconcile explicit DDL without assuming runtime order or discovering a database schema."""
import json
from typing import Any

from dataforge.asset_identity import AssetResolver
from dataforge.models import AssetRef, Diagnostic, ParseResult, column_key, operation_ids


def collect_schemas(results: list[tuple[dict[str, Any], ParseResult]], workspace: str, resolver: AssetResolver) -> dict[str, dict[str, Any]]:
    """Reconcile declared schemas by resolved asset identity and retain their evidence.

    Args:
        results: Source records paired with their parser results.
        workspace: Workspace identifier used to create stable evidence IDs.
        resolver: Resolver that applies the workspace's asset identity rules.

    Returns:
        Schema records keyed by resolved asset ID. Conflicting or incomplete declarations
        are marked unresolved and do not expose columns for wildcard expansion."""
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
        aid, _ = resolve(AssetRef(record["table"]), source, parsed)
        declarations.setdefault(aid, []).append((source, parsed, record))
        name = normalize(record["table"])
        if "." not in name:
            # Ambiguous unqualified DDL may affect any qualified candidate; never choose one.
            for candidate, declaration_source in qualified.get(name, []):
                if not resolver.visible_from(candidate, declaration_source, source):
                    continue
                possible, _ = resolve(AssetRef(candidate), source, parsed)
                if possible != aid:
                    declarations.setdefault(possible, []).append((source, parsed, {**record, "columns": None}))
    schemas = {}
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
    return schemas
