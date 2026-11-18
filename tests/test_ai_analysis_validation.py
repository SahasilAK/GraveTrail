"""Synthetic semantic gold: exact original evidence is necessary, never sufficient."""
import hashlib


def context(code, language="sql", job="job-a"):
    return {"unit": {"unit_id": "u", "file_id": "f", "path": "synthetic." + language,
                     "content_hash": hashlib.sha256(code.encode()).hexdigest(), "job_id": job,
                     "extension": "." + language, "code": code,
                     "start_offset": 0, "end_offset": len(code), "first": 1,
                     "last": code.count("\n") + 1}, "workspace_id": "w", "source_text": code, "settings": {}}


def response(ctx, **claims):
    unit = ctx["unit"]
    evidence = {key: unit[key] for key in ("unit_id", "file_id", "content_hash", "start_offset", "end_offset")}
    evidence.update(start_line=unit["first"], end_line=unit["last"])
    evidence["quote"] = ctx["source_text"][unit["start_offset"]:unit["end_offset"]]
    result = {"unit_id": unit["unit_id"], "coverage": {"status": "complete"}}
    for kind, items in claims.items():
        result[kind] = [{"evidence": evidence.copy(), **item} for item in items]
        if kind == "derivations":
            for item in result[kind]:
                offset = ctx["source_text"].find(item["expression"])
                item["expression_start_offset"] = max(offset, 0)
                item["expression_end_offset"] = max(offset, 0) + len(item["expression"])
    return result


def edge(source="raw.a", target="mart.b", operation="CREATE"):
    return {"source": source, "target": target, "operation": operation}


def derivation(expression="a.x + a.y AS total", **changes):
    return {"target_table": "mart.b", "target_column": "total", "expression": expression,
            "category": "expression", "scope": "", "branch": 0, "version": "", "ordinal": 0,
            "inputs": [{"table": "raw.a", "column": c, "role": "value"} for c in ("x", "y")],
            **changes}
