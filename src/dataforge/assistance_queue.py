"""Bounded, read-only diagnostic triage with explicit source-version-pinned AI requests."""
from typing import Any

import httpx

from dataforge.llm import assist_task, preview_assistance
from dataforge.store import Store

_ELIGIBLE = """FROM diagnostics d JOIN source_files f
    ON d.file_id=f.file_id AND d.workspace_id=f.workspace_id
    WHERE d.workspace_id=? AND d.severity IN ('warning','error')
    AND f.extension IN ('.sql','.sas') AND f.parsing_status IN ('success','partial','failed')
    AND coalesce(json_extract_string(f.metadata,'$.source_kind'),'files')<>'dbt'"""
_FIELDS = "d.*,f.relative_path,f.extension,f.content_hash"


def diagnostic_queue(store: Store, workspace: str) -> dict[str, Any]:
    """List up to one hundred current SQL and SAS diagnostics in severity order."""
    rows = store.rows(f"SELECT {_FIELDS} {_ELIGIBLE} ORDER BY CASE d.severity WHEN 'error' THEN 0 ELSE 1 END,f.relative_path,d.line,d.diagnostic_id LIMIT 101", [workspace])
    return {"items": rows[:100], "truncated": len(rows) > 100}


def _item(store: Store, workspace: str, diagnostic: str) -> dict[str, Any]:
    """Load a current workspace diagnostic or raise when it is no longer available."""
    rows = store.rows(f"SELECT {_FIELDS} {_ELIGIBLE} AND d.diagnostic_id=? LIMIT 1", [workspace, diagnostic])
    if not rows:
        raise ValueError("Diagnostic is not current; analyze the inventory and refresh this review")
    return rows[0]


def diagnostic_context(store: Store, workspace: str, diagnostic: str) -> dict[str, Any]:
    """Build a source-version-checked, bounded preview around a diagnostic line."""
    item = _item(store, workspace, diagnostic)
    source = store.file(item["file_id"])
    if source["workspace_id"] != workspace or source["content_hash"] != item["content_hash"]:
        raise ValueError("Source changed; refresh the diagnostic preview")
    lines = source["raw_content"].splitlines()
    line = item["line"]
    if not 1 <= line <= len(lines):
        raise ValueError("Diagnostic has no valid source line; analyze the file again")
    # Prefer a stored deterministic statement that contains the diagnostic's line.
    spans = store.rows("""SELECT s.start_line,s.end_line FROM statements s JOIN operations o
        ON s.statement_id=o.statement_id AND s.workspace_id=o.workspace_id
        WHERE s.workspace_id=? AND s.file_id=? AND s.content_hash=? AND o.method<>'llm'
        AND s.start_line<=? AND s.end_line>=? ORDER BY s.end_line-s.start_line,s.start_line LIMIT 1""",
        [workspace, item["file_id"], item["content_hash"], line, line])
    first, last = (spans[0]["start_line"], spans[0]["end_line"]) if spans else (max(1, line - 3), min(len(lines), line + 12))
    # Large statements require an explicit range choice instead of an enormous automatic preview.
    first, last = max(first, line - 3), min(last, line + 36)
    return {**item, "first": first, "last": last, "line_count": len(lines),
            "code": "\n".join(lines[first - 1:last]), "bounded_context": not spans or first != spans[0]["start_line"] or last != spans[0]["end_line"],
            "task": "sql_lineage" if item["extension"] == ".sql" else "sas_lineage"}


def preview_review(store: Store, workspace: str, diagnostic: str,
                   first: int | None = None, last: int | None = None) -> dict[str, Any]:
    """Preview the routed, complete review request without provider calls or writes."""
    item = diagnostic_context(store, workspace, diagnostic)
    first = item['first'] if first is None else first
    last = item['last'] if last is None else last
    if type(first) is not int or type(last) is not int or not 1 <= first <= last <= item['line_count']:
        raise ValueError('Select a valid source line range')
    source = store.file(item['file_id'])
    if source['content_hash'] != item['content_hash']:
        raise ValueError('Source changed; refresh the diagnostic preview')
    prepared = preview_assistance(store, workspace, item['file_id'], first, last, item['task'],
                                  expected_hash=item['content_hash'])
    return {**item, **prepared}


def request_review(
    store: Store,
    workspace: str,
    diagnostic: str,
    content_hash: str,
    first: int,
    last: int,
    transport: httpx.BaseTransport | None = None,
    *, expected_job: str | None = None, expected_request: str = '',
) -> dict[str, Any]:
    """Request AI review for a diagnostic only if its source version is still current.

    Args:
        store: Workspace store containing the diagnostic and source.
        workspace: Workspace identifier.
        diagnostic: Diagnostic identifier to review.
        content_hash: Expected hash of the source version shown to the reviewer.
        first: First source line to include.
        last: Last source line to include.
        transport: Optional provider transport passed through to the AI service.

    Raises:
        ValueError: If the diagnostic or source version is stale, or the line bounds are invalid.
    """
    item = _item(store, workspace, diagnostic)
    if item["content_hash"] != content_hash:
        raise ValueError("Source changed; refresh the diagnostic preview")
    if type(first) is not int or type(last) is not int:
        raise ValueError("Source line bounds must be integers")
    task = "sql_lineage" if item["extension"] == ".sql" else "sas_lineage"
    return assist_task(store, workspace, item["file_id"], first, last, task,
                       transport=transport, expected_hash=content_hash, expected_job=expected_job,
                       expected_request=expected_request)
