"""Query-bound continuation cursors and serialized response budgets."""
import base64
import hashlib
import json
from typing import Any

from dataforge.agent.contracts import AgentError, QueryOptions, compact


def page(items: list[Any], options: QueryOptions, key: Any, **metadata: Any) -> dict[str, Any]:
    """Return one size-bounded page with a query-bound continuation cursor.

    Args:
        items: Ordered result records to page.
        options: Validated cursor, page-size, and response-budget options.
        key: Query identity used to reject cursors from other requests.
        **metadata: Additional response fields included with every page.

    Returns:
        A response containing selected items, counts, completeness, and a cursor.

    Raises:
        AgentError: If the cursor is invalid or the response budget is too small.
    """
    fingerprint = hashlib.sha256(compact(key).encode()).hexdigest()[:24]
    offset = 0
    if options.cursor:
        try:
            record = json.loads(base64.urlsafe_b64decode(options.cursor.encode()))
            offset = record["offset"]
            if record["query"] != fingerprint or type(offset) is not int or not 0 <= offset < len(items):
                raise ValueError
        except (ValueError, KeyError, TypeError, UnicodeError):
            raise AgentError("invalid_cursor", "Cursor is invalid, stale or belongs to another query") from None

    def envelope(selected: list[Any]) -> dict[str, Any]:
        """Build response metadata for the selected records."""
        end = offset + len(selected)
        cursor = base64.urlsafe_b64encode(compact({"query": fingerprint, "offset": end}).encode()).decode()
        return {**metadata, "items": selected, "count": len(selected), "total": len(items),
                "next_cursor": cursor if end < len(items) else None,
                "complete": end == len(items) and not metadata.get("boundaries")
                and metadata.get("analysis_current", True)}

    selected = []
    for item in items[offset:offset + options.limit]:
        candidate = envelope([*selected, item])
        if len(compact(candidate)) > options.max_chars:
            if not selected:
                raise AgentError("budget_too_small", "One record exceeds max_chars; request a larger budget or source range",
                                 minimum_chars=len(compact(candidate)))
            break
        selected.append(item)
    result = envelope(selected)
    if len(compact(result)) > options.max_chars:
        raise AgentError("budget_too_small", "Response metadata exceeds max_chars")
    return result
