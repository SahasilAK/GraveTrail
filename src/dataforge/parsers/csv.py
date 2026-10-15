"""Streaming CSV metadata extraction; never interprets values as code."""
from __future__ import annotations

import csv
import hashlib
import io
import json

from dataforge.models import AssetRef, Diagnostic, ParseResult, file_asset


def parse_csv(content: str, path: str, sample_size: int = 25) -> ParseResult:
    result = ParseResult(assets=[AssetRef(file_asset(path), kind="file")])
    try:
        dialect = csv.Sniffer().sniff(content[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(content), dialect)
    header = next(reader, [])
    if not header:
        result.diagnostics.append(Diagnostic("CSV is empty", severity="warning"))
    preview, count, inconsistent = [], 0, 0
    try:
        for row in reader:
            count += 1
            inconsistent += len(row) != len(header)
            if len(preview) < sample_size:
                preview.append(row)
    except csv.Error:
        result.diagnostics.append(Diagnostic("Malformed CSV record; row count is partial", count + 2, "error"))
    if inconsistent:
        result.diagnostics.append(Diagnostic(f"{inconsistent} CSV rows differ from header width"))

    def infer(index):
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
