"""Process-local request admission and offline, original-coordinate context chunks."""
import re
import threading
from contextlib import contextmanager
from pathlib import Path

from dataforge.models import statements
from dataforge.parsers.sas import strip_comments

_LOCK = threading.Lock()
_ACTIVE = {}
_MAINTENANCE = set()


@contextmanager
def block_requests_for_maintenance(home):
    identity = str(Path(home).resolve())
    with _LOCK:
        if any(key[0] == identity and count for key, count in _ACTIVE.items()):
            raise ValueError('An active AI request blocks maintenance')
        _MAINTENANCE.add(identity)
    try:
        yield
    finally:
        with _LOCK:
            _MAINTENANCE.discard(identity)


def has_active_requests(home, workspace=''):
    with _LOCK:
        return any(count and key[0] == str(Path(home).resolve()) and (not workspace or key[1] == workspace)
                   for key, count in _ACTIVE.items())


@contextmanager
def request_slot(home, workspace, limit):
    """Fail fast rather than accumulate queued source payloads; always release capacity."""
    key = (str(Path(home).resolve()), workspace)
    with _LOCK:
        if key[0] in _MAINTENANCE:
            raise ValueError('Storage maintenance is active; retry when it finishes')
        if _ACTIVE.get(key, 0) >= limit or sum(_ACTIVE.values()) >= 8:
            raise ValueError("LLM requests are busy; retry after an active request finishes")
        _ACTIVE[key] = _ACTIVE.get(key, 0) + 1
    try:
        yield
    finally:
        with _LOCK:
            remaining = _ACTIVE[key] - 1
            if remaining:
                _ACTIVE[key] = remaining
            else:
                del _ACTIVE[key]


def context_chunks(code, extension, first, last, max_chars):
    """Never split a statement/SAS block or silently omit an oversized unit."""
    lines = code.splitlines()
    if not 1 <= first <= last <= len(lines) or not 1 <= max_chars <= 100000:
        raise ValueError("Invalid context range or chunk budget")
    spans, block_start, block_kind, macro_depth = [], None, "", 0
    for raw, start, end in statements(code, sas=extension == ".sas"):
        clean = strip_comments(raw).strip().casefold()
        if extension == ".sas":
            if re.match(r"%macro\b", clean):
                macro_depth += 1
                block_start = block_start or start
            if macro_depth:
                if re.match(r"%mend\b", clean):
                    macro_depth -= 1
                    if not macro_depth:
                        spans.append((block_start, end))
                        block_start, block_kind = None, ""
                continue
            header = re.match(r"(data|proc)\b\s*(\w*)", clean)
            if header and block_start is None:
                block_start = start
                # Unknown/interactive PROCs keep context through QUIT; RUN need not end them.
                run_procs = {"sort", "means", "summary", "transpose", "import", "export", "print", "freq", "contents"}
                block_kind = "run" if header.group(1) == "data" or header.group(2) in run_procs else "quit"
            if block_start is not None:
                if re.match(r"quit\b", clean) or (block_kind == "run" and re.match(r"run\b", clean)):
                    spans.append((block_start, end))
                    block_start, block_kind = None, ""
                continue
        spans.append((start, end))
    if block_start is not None:
        spans.append((block_start, len(lines)))
    # Statements sharing a source line cannot be represented as separate line-range previews.
    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    selected = []
    for start, end in merged:
        if end < first or start > last:
            continue
        if start < first or end > last:
            raise ValueError("Select complete statements or SAS blocks for chunking")
        if len("\n".join(lines[start - 1:end])) > max_chars:
            raise ValueError("A statement or SAS block exceeds the chunk budget; increase it or select another range")
        if selected and len("\n".join(lines[selected[-1][0] - 1:end])) <= max_chars:
            selected[-1] = (selected[-1][0], end)
        else:
            selected.append((start, end))
        if len(selected) > 50:
            raise ValueError("Selection exceeds 50 chunks; choose a smaller range")
    if not selected:
        raise ValueError("No complete statements in the selected range")
    return [{"first": a, "last": b, "code": "\n".join(lines[a - 1:b])} for a, b in selected]
