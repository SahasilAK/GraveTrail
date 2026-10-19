"""Parser contracts. No persistence or presentation dependencies."""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field


def stable_id(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:32]


def canonical(name: str) -> str:
    parts = re.findall(r'"(?:""|[^"])*"|`(?:``|[^`])*`|\[(?:\]\]|[^\]])*\]|[^.]+', name.strip())
    normalized = []
    for part in parts:
        value = part.strip()
        if value[:1] in {'"', '`', '['}:
            value = value[1:-1].replace('""', '"').replace('``', '`').replace(']]', ']')
        value = value.casefold()
        normalized.append('"' + value.replace('"', '""') + '"' if '.' in value else value)
    return ".".join(normalized)


def file_asset(path: str) -> str:
    return "file:" + path.replace("\\", "/").removeprefix("./")


def column_key(name: str, case_sensitive: bool = False) -> str:
    value = name.strip()
    if value in {'', '*'}:
        return value
    for opening, closing in [('"', '"'), ('`', '`'), ('[', ']')]:
        if len(value) >= 2 and value.startswith(opening) and value.endswith(closing):
            return 'column:' + value[1:-1].replace(closing * 2, closing)
    return 'column:' + (value if case_sensitive else value.casefold())


@dataclass
class AssetRef:
    name: str
    temporary: bool = False
    kind: str = "table"


@dataclass
class Usage:
    table: str
    column: str
    context: str = "SELECT"
    alias: str = ""
    expression: str = ""
    status: str = "verified"
    wildcard_safe: bool = False


@dataclass
class Operation:
    kind: str
    sources: list[AssetRef]
    targets: list[AssetRef]
    code: str
    start: int
    end: int
    method: str = "parser"
    confidence: float = 1.0
    usages: list[Usage] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    derivations: list[dict] = field(default_factory=list)
    evidence_key: str = ''
    table_pairs: list[tuple[int, int]] | None = None


def operation_ids(workspace: str, metadata: dict, index: int, operation: Operation) -> tuple[str, str]:
    """Share canonical host evidence identity across table and column materializers."""
    sid = stable_id(workspace, metadata['file_id'], operation.evidence_key or str(index), metadata['content_hash'])
    return sid, stable_id(sid, operation.kind)


@dataclass
class Diagnostic:
    message: str
    line: int = 1
    severity: str = "warning"
    symbol: str = ""


@dataclass
class ParseResult:
    operations: list[Operation] = field(default_factory=list)
    assets: list[AssetRef] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ParseResult:
        return cls(
            operations=[Operation(**{**o,
                "sources": [AssetRef(**a) for a in o["sources"]],
                "targets": [AssetRef(**a) for a in o["targets"]],
                "usages": [Usage(**u) for u in o["usages"]]}) for o in data["operations"]],
            assets=[AssetRef(**a) for a in data["assets"]],
            diagnostics=[Diagnostic(**d) for d in data["diagnostics"]], metadata=data["metadata"],
        )


def statements(text: str, sas: bool = False):
    """Split at unquoted semicolons, preserving offsets, comments and exact evidence."""
    start = 0
    i = 0
    quote = None
    block = False
    line_comment = False
    dollar = None
    while i < len(text):
        c = text[i]
        nxt = text[i:i + 2]
        if line_comment:
            if c == "\n":
                line_comment = False
        elif block:
            if nxt == "*/":
                block = False
                i += 1
        elif dollar:
            if text.startswith(dollar, i):
                i += len(dollar) - 1
                dollar = None
        elif quote:
            if c == quote or (quote == "]" and c == "]"):
                if i + 1 < len(text) and text[i + 1] == c:
                    i += 1
                else:
                    quote = None
        elif nxt == "/*":
            block = True
            i += 1
        elif nxt == "--":
            line_comment = True
            i += 1
        elif c in "'\"`[":
            quote = "]" if c == "[" else c
        elif c == "$" and (m := re.match(r"\$[A-Za-z_0-9]*\$", text[i:])):
            dollar = m.group()
            i += len(dollar) - 1
        elif c == ";":
            raw = text[start:i + 1]
            if raw.strip():
                leading = len(raw) - len(raw.lstrip())
                a = start + leading
                yield raw.strip(), text.count("\n", 0, a) + 1, text.count("\n", 0, i) + 1
            if sas and (inline := re.match(r"\s*(?:datalines|cards)(4)?\s*;\s*$", raw, re.I)):
                terminator = ";;;;" if inline.group(1) else ";"
                stop = re.search(r"(?m)^[ \t]*" + re.escape(terminator) + r"[ \t]*\r?$", text[i + 1:])
                if stop is None:
                    return
                i += 1 + stop.end()
                start = i
                continue
            start = i + 1
        i += 1
    if text[start:].strip():
        raw = text[start:]
        leading = len(raw) - len(raw.lstrip())
        yield raw.strip(), text.count("\n", 0, start + leading) + 1, text.count("\n") + 1
