"""Reconcile explicit DDL without assuming runtime order or discovering a database schema."""
import json

from dataforge.models import AssetRef, Diagnostic, stable_id


def collect_schemas(results, workspace, normalize, resolve):
    records = [(source, parsed, record) for source, parsed in results
               for record in parsed.metadata.get("declared_schemas", [])]
    qualified = {}
    for _, _, record in records:
        name = normalize(record["table"])
        if "." in name:
            qualified.setdefault(name.rsplit(".", 1)[-1], {})[name] = record["table"]
    declarations = {}
    for source, parsed, record in records:
        aid, _ = resolve(AssetRef(record["table"]), source, parsed)
        declarations.setdefault(aid, []).append((source, parsed, record))
        name = normalize(record["table"])
        if "." not in name:
            # Ambiguous unqualified DDL may affect any qualified candidate; never choose one.
            for candidate in qualified.get(name, {}).values():
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
                names = [normalize(c["name"]) for c in columns]
                valid = valid and len(set(names)) == len(names)
                signatures.add(json.dumps([(normalize(c["name"]), c["type"]) for c in columns]))
            evidence.append({"file_id": source["file_id"], "relative_path": source["relative_path"],
                "source_hash": source["content_hash"], "start_line": record["start_line"],
                "end_line": record["end_line"], "statement_id": stable_id(workspace, source["file_id"],
                    str(record["operation_index"]), source["content_hash"])})
        valid = valid and len(signatures) == 1
        schemas[aid] = {"schema_status": "declared" if valid else "unresolved",
            "columns": records[0][2]["columns"] if valid else [], "schema_evidence": evidence}
        if not valid and any(record["columns"] for _, _, record in records):
            for _, parsed, record in records:
                message = f"Schema for {name} is conflicting, incomplete or changed; wildcard expansion disabled"
                if not any(d.message == message for d in parsed.diagnostics):
                    parsed.diagnostics.append(Diagnostic(message, record["start_line"], symbol=name))
    return schemas
