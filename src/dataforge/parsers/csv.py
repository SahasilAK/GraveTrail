"""Streaming CSV metadata extraction; never interprets values as code."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Iterator

from dataforge.models import AssetRef, Diagnostic, ParseResult, file_asset


def bounded_records(content: str, dialect: csv.Dialect, max_columns: int = 4096,
                    max_record_chars: int = 1_000_000) -> Iterator[str]:
    """Yield CSV lines while enforcing width and logical-record size limits.

    Args:
        content: Complete decoded CSV text.
        dialect: Detected or default CSV dialect.
        max_columns: Maximum number of fields permitted in one record.
        max_record_chars: Maximum number of characters in a logical record.

    Yields:
        Original lines from the CSV text.

    Raises:
        ValueError: If a logical record exceeds either configured limit.
    """
    quoted, field_start, fields, chars = False, True, 1, 0
    for line in io.StringIO(content):
        chars += len(line)
        if chars > max_record_chars:
            raise ValueError("CSV record exceeds 1,000,000 character limit")
        i = 0
        while i < len(line):
            c = line[i]
            if quoted:
                if c == dialect.quotechar and i + 1 < len(line) and line[i + 1] == c:
                    i += 1
                elif c == dialect.quotechar:
                    quoted = False
            elif c == dialect.quotechar and field_start:
                quoted, field_start = True, False
            elif c == dialect.delimiter:
                fields += 1
                field_start = True
                if fields > max_columns:
                    raise ValueError("CSV exceeds 4,096 column limit")
            elif not (field_start and dialect.skipinitialspace and c == ' '):
                field_start = False
            i += 1
        if not quoted:
            field_start, fields, chars = True, 1, 0
        yield line


def parse_csv(content: str, path: str, sample_size: int = 25) -> ParseResult:
    """Extract CSV header, row counts, a bounded preview, and sampled column types.

    Args:
        content: Decoded CSV text.
        path: Source-relative path used to identify the file asset.
        sample_size: Maximum number of data rows used for preview and type sampling.

    Returns:
        Parse result with file metadata and diagnostics for malformed rows.
    """
    result = ParseResult(assets=[AssetRef(file_asset(path), kind="file")])
    try:
        dialect = csv.Sniffer().sniff(content[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(bounded_records(content, dialect), dialect)
    try:
        header = next(reader, [])
    except (csv.Error, ValueError):
        result.diagnostics.append(Diagnostic("CSV header is malformed or exceeds width/field/record limits", 1, "error"))
        return result
    if not header:
        result.diagnostics.append(Diagnostic("CSV is empty", severity="warning"))
    preview, count, inconsistent = [], 0, 0
    try:
        for row in reader:
            count += 1
            inconsistent += len(row) != len(header)
            if len(preview) < sample_size:
                preview.append(row)
    except (csv.Error, ValueError):
        result.diagnostics.append(Diagnostic("Malformed or oversized CSV record; row count is partial", count + 2, "error"))
    if inconsistent:
        result.diagnostics.append(Diagnostic(f"{inconsistent} CSV rows differ from header width"))

    def infer(index: int) -> str:
        """Infer a display type from nonempty values in one sampled column.

        Args:
            index: Zero-based column position in the header.

        Returns:
            Sampled integer, number, or text label, or ``unknown`` when empty.
        """
        values = [r[index] for r in preview if len(r) > index and r[index].strip()]
        if not values:
            return "unknown"
        try:
            for v in values:
                int(v)
            return "integer (sampled)"
        except ValueError:
            try:
                for v in values:
                    float(v)
                return "number (sampled)"
            except ValueError:
                return "text (sampled)"

    result.metadata = {"columns": [{"name": name, "type": infer(i)} for i, name in enumerate(header)],
                       "row_count": count, "delimiter": dialect.delimiter, "header_presence": "assumed first row",
                       "preview": preview, "schema_fingerprint": hashlib.sha256(json.dumps(header).encode()).hexdigest()}
    return result
