"""Task-specific advisory results, grounded against exact source and parser attribution."""
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from dataforge.models import canonical
from dataforge.parsers.sas import parse_sas
from dataforge.parsers.sql import parse_sql


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=10000)


class ColumnClaim(Citation):
    source: str = Field(min_length=1, max_length=500)
    column: str = Field(min_length=1, max_length=500)
    context: str = Field(min_length=1, max_length=50)
    explanation: str = Field(max_length=5000)
    confidence: float = Field(ge=0, le=1)


class ColumnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    columns: list[ColumnClaim] = Field(default_factory=list, max_length=100)
    unresolved_symbols: list[str] = Field(default_factory=list, max_length=100)


class Explanation(Citation):
    text: str = Field(min_length=1, max_length=5000)
    assets: list[str] = Field(default_factory=list, max_length=100)


class ExplanationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    explanations: list[Explanation] = Field(default_factory=list, max_length=100)
    unresolved_symbols: list[str] = Field(default_factory=list, max_length=100)


TASK_SCHEMAS = {"column_usage": ColumnResponse, "code_explanation": ExplanationResponse}


def validate_advisory(
    response: ColumnResponse | ExplanationResponse,
    source: dict[str, Any],
    known: set[str],
    first: int,
    last: int,
    settings: dict[str, Any],
) -> ColumnResponse | ExplanationResponse:
    """Validate citations and parser attribution while keeping generated prose advisory.

    Args:
        response: Structured advisory claims to validate.
        source: Source record containing raw content and its extension.
        known: Asset names available to the current operation.
        first: First source line included in the evidence window.
        last: Last source line included in the evidence window.
        settings: Parser options for the source.

    Returns:
        The same response after its citations and claims pass validation.

    Raises:
        ValueError: If a citation or claim is outside the supplied evidence or unsupported.
    """
    lines = source["raw_content"].splitlines()
    identity = (lambda name: name) if settings.get("case_sensitive", False) else canonical
    known = {identity(name) for name in known}
    parsed = (parse_sas(source["raw_content"], settings.get("library_mappings"), settings.get("macros"), settings.get("dialect", ""))
              if source["extension"] == ".sas" else parse_sql(source["raw_content"], settings.get("dialect", "")))
    items = response.columns if isinstance(response, ColumnResponse) else response.explanations
    for item in items:
        if not first <= item.start_line <= item.end_line <= min(last, len(lines)):
            raise ValueError("Citation range is outside supplied source evidence")
        if item.quote not in "\n".join(lines[item.start_line - 1:item.end_line]):
            raise ValueError("Citation quote is not exact source evidence")
        # Match complete operations parsed in original context, never reparsed quote fragments.
        operations = [op for op in parsed.operations
                      if op.start == item.start_line and op.end == item.end_line
                      and (op.code.strip() == item.quote.strip()
                           or item.quote == "\n".join(lines[op.start - 1:op.end]))]
        if isinstance(item, ColumnClaim):
            if identity(item.source) not in known or item.column == "*":
                raise ValueError("Column source is unknown or wildcard coverage is uncertain")
            if not any(identity(u.table) == identity(item.source)
                       and identity(u.column) == identity(item.column)
                       and u.context == item.context and u.status == "verified"
                       for op in operations for u in op.usages):
                raise ValueError("Column lacks unambiguous direct parser attribution in its quote")
        else:
            evidenced = {identity(ref.name) for op in operations for ref in [*op.sources, *op.targets]}
            if any(identity(name) not in known or identity(name) not in evidenced for name in item.assets):
                raise ValueError("Explanation asset is unknown or absent from cited operation")
    return response
