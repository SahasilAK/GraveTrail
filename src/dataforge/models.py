"""Parser contracts. No persistence or presentation dependencies."""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field


def stable_id(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:32]


def canonical(name: str) -> str:
    # SQL parsers supply unquoted identifier components; SAS may supply raw names.
    return ".".join(p.strip().strip('`"[]').casefold() for p in name.strip().split("."))


def file_asset(path: str) -> str:
    return "file:" + path.replace("\\", "/").removeprefix("./")


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
            start = i + 1
        i += 1
    if text[start:].strip():
        raw = text[start:]
        leading = len(raw) - len(raw.lstrip())
        yield raw.strip(), text.count("\n", 0, start + leading) + 1, text.count("\n") + 1
