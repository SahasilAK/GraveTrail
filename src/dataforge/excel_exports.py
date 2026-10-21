"""Bounded, literal-text XLSX reports over the shared ordered path contract."""
from __future__ import annotations

import io
import math
import tempfile
import time
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

import xlsxwriter

from dataforge.asset_identity import asset_label

XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
STEP_COLUMNS = 8
MAX_RELATIONSHIPS = 20000
MAX_EVIDENCE = 20000
MAX_TEXT_BYTES = 32 * 1024 * 1024
MAX_WORKBOOK_BYTES = 64 * 1024 * 1024
MAX_SECONDS = 30

STEP_HEADERS = ['Path ID', 'Relationship number', 'Source dataset', 'Target dataset',
    'Relationship / operation', 'Transformation summary', 'Evidence status', 'Confidence',
    'Temporary stages', 'Intermediate datasets', 'Evidence count', 'Evidence IDs',
    'Boundary / limitation', 'Source asset ID', 'Target asset ID']
EVIDENCE_HEADERS = ['Evidence ID', 'Source asset ID', 'Target asset ID', 'Source relative path',
    'Original line start', 'Original line end', 'Statement ID', 'Operation ID',
    'Source content hash', 'Extraction method', 'Evidence status']
COVERAGE = {'root': 'No further known upstream in analyzed graph',
    'terminal': 'No further known downstream in analyzed graph',
    'depth': 'Depth limit; boundary, not an original source', 'cycle': 'Cycle; finite path only',
    'relationship_limit': 'Relationship limit; remaining dependencies omitted',
    'unresolved': 'Unresolved evidence; traversal stopped, source or terminal not established'}


def lineage_xlsx(
    report: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    scope: dict[str, Any],
    *,
    include_evidence: bool = False,
    include_source_text: bool = False,
) -> tuple[bytes, dict[str, Any]]:
    """Create a bounded XLSX workbook for ordered lineage paths and evidence.

    Args:
        report: Ordered path report with evidence and truncation boundaries.
        nodes: Asset attributes keyed by asset ID for display labels.
        scope: Workspace, revision, filter, and export metadata.
        include_evidence: Whether to add an offline evidence worksheet.
        include_source_text: Whether evidence rows also include source excerpts.

    Returns:
        Workbook bytes and counts, revision, completeness, and warning metadata.

    Raises:
        ValueError: If path data is inconsistent or workbook size, time, or text limits are exceeded.
    """
    started = time.monotonic()
    if not report['paths']:
        raise ValueError('Select an existing exact asset to export lineage')
    if include_source_text and not include_evidence:
        raise ValueError('Source text requires the Evidence sheet')
    text_bytes = 0

    def bounded_row(values: list[Any]) -> list[Any]:
        """Check row text and workbook time budgets before returning the row unchanged."""
        nonlocal text_bytes
        if time.monotonic() - started > MAX_SECONDS:
            raise ValueError('Workbook time limit exceeded; narrow the selection and retry')
        for value in values:
            if not isinstance(value, str):
                continue
            if len(value.encode('utf-16-le')) // 2 > 32767:
                raise ValueError('Excel cell exceeds 32767 characters; shorten the label or exclude source text')
            text_bytes += len(value.encode('utf-8'))
            if text_bytes > MAX_TEXT_BYTES:
                raise ValueError('Workbook text limit exceeded; narrow the selection')
        return values

    warnings = list(scope.get('warnings', []))
    if report['truncated']:
        warnings.append('Dependencies omitted by path, depth, cycle, relationship or graph limits; see Coverage.')
    if report.get('boundaries'):
        warnings.append(f"Unresolved evidence: {len(report['boundaries'])} support(s); accepted parallel support may still establish a path.")
    if not include_evidence:
        warnings.append('Evidence sheet excluded; evidence IDs/status are references, not offline citations.')
    warnings.append('Static analysis can have unknown or unsupported coverage; a known boundary is not proof of origin.')

    def label(aid: str) -> str:
        """Format an asset ID using its registered asset label."""
        return asset_label(nodes[aid])

    path_rows, step_rows, evidence = [], [], {e['edge_id']: e for e in report.get('boundaries', [])}
    if len(evidence) > MAX_EVIDENCE:
        raise ValueError('Workbook relationship/evidence limit exceeded; narrow the selection')
    step_width = min(STEP_COLUMNS, max(len(p['node_ids']) for p in report['paths']))
    for path in report['paths']:
        ids = path['node_ids']
        # The report contract stores dependency order even for upstream traversal.
        if len(ids) != len(path['steps']) + 1 or any(
            (s['source_id'], s['target_id']) != pair
            for s, pair in zip(path['steps'], zip(ids, ids[1:]))
        ):
            raise ValueError('Inconsistent source-to-target path; retry export')
        pid = f"P{path['path_id']:03d}"
        boundary = COVERAGE.get(path['boundary'], path['boundary'])
        collapsed = any(s['intermediates'] for s in path['steps'])
        notes = ['Shared datasets can occur in other paths; branches do not imply execution sequence.']
        if collapsed:
            notes.append('Collapsed temporary stages; ordered retained intermediates are in Lineage Steps.')
        if report['truncated']:
            notes.append('Bounded export; additional dependencies may be omitted.')
        segments = max(1, math.ceil((len(ids) - 1) / (STEP_COLUMNS - 1)))
        for segment in range(segments):
            start = segment * (STEP_COLUMNS - 1)
            subset = ids[start:start + STEP_COLUMNS]
            segment_note = f'Continuation segment {segment + 1}/{segments}; boundary dataset repeated.' if segments > 1 else ''
            path_rows.append(bounded_row([pid, label(report['selected_asset']), boundary, *[label(n) for n in subset],
                *[''] * (step_width - len(subset)), len(subset) - 1, len(ids) - 1,
                segment + 1, f'{start + 1}–{start + len(subset)}', ' '.join([*notes, segment_note])]))
        for number, step in enumerate(path['steps'], 1):
            citations = sorted(step['evidence'], key=lambda e: e['edge_id'])
            kinds = ', '.join(sorted({e['kind'] for e in citations if e.get('kind')}))
            status = ', '.join(sorted({e.get('status') or 'unknown' for e in citations})) or 'unknown'
            confidences = [e['confidence'] for e in citations if e.get('confidence') is not None]
            # A range retains differing observations instead of inventing an aggregate confidence.
            confidence = (confidences[0] if confidences and len(set(confidences)) == 1
                          else f'{min(confidences):g}–{max(confidences):g}' if confidences else '')
            step_rows.append(bounded_row([pid, number, label(step['source_id']), label(step['target_id']), kinds,
                kinds, status, confidence, 'Collapsed' if step['intermediates'] else 'Included / none collapsed',
                ' → '.join(step['intermediates']), len(citations), ', '.join(e['edge_id'] for e in citations),
                boundary + ('; bounded export' if report['truncated'] else ''), step['source_id'], step['target_id']]))
            for citation in citations:
                evidence[citation['edge_id']] = citation
            if len(step_rows) > MAX_RELATIONSHIPS or len(evidence) > MAX_EVIDENCE:
                raise ValueError('Workbook relationship/evidence limit exceeded; narrow the selection')
        if time.monotonic() - started > MAX_SECONDS:
            raise ValueError('Workbook time limit exceeded; narrow the selection and retry')
    metadata = {'path_count': len(report['paths']), 'segment_count': len(path_rows),
        'relationship_count': len(step_rows), 'evidence_count': len(evidence),
        'exported_evidence_count': len(evidence) if include_evidence else 0,
        'revision': scope.get('revision', 'unknown'),
        'complete': report.get('complete', not report['truncated']) and not report['truncated']
                    and scope.get('analysis_current', True), 'warnings': warnings}
    headers = ['Path ID', 'Selected asset', 'Coverage',
        'Step 1 - Starting dataset', *[f'Step {i}' for i in range(2, step_width + 1)],
        'Dependency count', 'Full path dependency count', 'Segment', 'Dataset step range', 'Notes']
    evidence_rows = [bounded_row([e['edge_id'], e.get('source_id', ''), e.get('target_id', ''),
        e.get('relative_path', ''), e.get('start_line', ''), e.get('end_line', ''),
        e.get('statement_id', ''), e.get('operation_id', ''), e.get('source_hash', ''),
        e.get('method', ''), e.get('status', 'unknown'), *([e.get('code', '')] if include_source_text else [])])
        for _, e in sorted(evidence.items())] if include_evidence else []

    output, text_bytes = io.BytesIO(), 0
    with tempfile.TemporaryDirectory(prefix='gravetrail-xlsx-') as temporary:
        with xlsxwriter.Workbook(output, {'constant_memory': True, 'tmpdir': temporary,
                'strings_to_formulas': False, 'strings_to_urls': False, 'strings_to_numbers': False}) as book:
            book.set_properties({'title': 'GraveTrail ordered lineage', 'comments': 'Static data dependencies'})
            header_format = book.add_format({'bold': True, 'bg_color': '#233D52', 'font_color': '#FFFFFF',
                'text_wrap': True, 'valign': 'top', 'font_name': 'Calibri', 'font_size': 11})
            formats = [book.add_format({'bg_color': color, 'text_wrap': True, 'valign': 'top',
                'font_name': 'Calibri', 'font_size': 11}) for color in ['#FFFFFF', '#EDF3F7']]
            date_format = book.add_format({'num_format': 'yyyy-mm-dd hh:mm:ss', 'font_name': 'Calibri',
                'align': 'left', 'valign': 'top', 'bg_color': '#FFF1D6'})
            note_format = book.add_format({'text_wrap': True, 'valign': 'top', 'font_name': 'Calibri',
                'font_color': '#6B3F08', 'bg_color': '#FFF1D6'})

            def write_row(
                sheet: xlsxwriter.worksheet.Worksheet,
                row: int,
                values: list[Any],
                fmt: xlsxwriter.format.Format,
                start_col: int = 0,
            ) -> None:
                """Write a row using literal text and bounded numeric/date cell handling."""
                nonlocal text_bytes
                if time.monotonic() - started > MAX_SECONDS:
                    raise ValueError('Workbook time limit exceeded; narrow the selection and retry')
                for col, value in enumerate(values, start_col):
                    if isinstance(value, datetime):
                        sheet.write_datetime(row, col, value.replace(tzinfo=None), date_format)
                    elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                        sheet.write_number(row, col, value, fmt)
                    else:
                        value = '' if value is None else str(value)
                        # Check UTF-16 units too: Excel's cell limit counts surrogate pairs.
                        if len(value.encode('utf-16-le')) // 2 > 32767:
                            raise ValueError('Excel cell exceeds 32767 characters; shorten the label or exclude source text')
                        text_bytes += len(value.encode('utf-8'))
                        if text_bytes > MAX_TEXT_BYTES:
                            raise ValueError('Workbook text limit exceeded; narrow the selection')
                        sheet.write_string(row, col, value, fmt)

            def sheet_table(
                name: str,
                columns: list[str],
                rows: list[list[Any]],
                scope_rows: Iterable[tuple[str, Any]] = (),
            ) -> xlsxwriter.worksheet.Worksheet:
                """Create a formatted, filterable worksheet with optional scope rows."""
                sheet = book.add_worksheet(name)
                sheet.hide_gridlines(2)
                sheet.set_landscape()
                sheet.set_paper(9)
                sheet.set_print_scale(100)
                sheet.set_column(0, 0, 13)
                sheet.set_column(1, len(columns) - 1, 29)
                sheet.set_column(len(columns) - 1, len(columns) - 1, 50)
                for col, heading in enumerate(columns):
                    if heading in {'Segment', 'Relationship number', 'Evidence count', 'Dependency count', 'Full path dependency count'}:
                        sheet.set_column(col, col, 15)
                    elif heading == 'Dataset step range':
                        sheet.set_column(col, col, 19)
                for i, values in enumerate(scope_rows):
                    sheet.set_row(i, 34)
                    # Scope text spans the sheet; merged cells never enter the sortable table.
                    write_row(sheet, i, [values[0]], header_format)
                    sheet.merge_range(i, 1, i, len(columns) - 1, '', note_format)
                    write_row(sheet, i, [values[1]], note_format, 1)
                first = len(scope_rows)
                sheet.set_row(first, 44)
                write_row(sheet, first, columns, header_format)
                for i, values in enumerate(rows, first + 1):
                    sheet.set_row(i, 64)
                    write_row(sheet, i, values, formats[(i - first - 1) % 2])
                sheet.autofilter(first, 0, first + len(rows), len(columns) - 1)
                sheet.freeze_panes(first + 1, 2)
                sheet.repeat_rows(first, first)
                sheet.print_area(0, 0, first + len(rows), len(columns) - 1)
                return sheet

            exported_at = datetime.fromisoformat(scope.get('export_time', datetime.now(timezone.utc).isoformat()))
            scope_rows = [('GraveTrail', 'Steps show data dependencies, not runtime execution order.'),
                ('Workspace', scope.get('workspace', 'unknown')),
                ('Selection', f"{label(report['selected_asset'])} [{report['selected_asset']}] · {report['direction']} traversal"),
                ('Revision', str(metadata['revision'])),
                ('Export time', exported_at), ('Timezone', exported_at.strftime('%z') or 'UTC'),
                ('Scope', f"Depth {report['max_depth']}; paths {report['max_paths']}; "
                    f"relationship limit {scope.get('max_relationships', MAX_RELATIONSHIPS)}; "
                    f"temporary stages: {scope.get('temporary_policy', 'as selected')}; filters: {scope.get('filters', 'as selected')}"),
                ('Counts', f"{metadata['path_count']} unique paths; {metadata['segment_count']} segment rows; "
                    f"{metadata['relationship_count']} path relationships; {metadata['evidence_count']} evidence records; "
                    f"{metadata['exported_evidence_count']} evidence records included offline"),
                ('Legend', 'Dataset steps start at 1. Relationship 1 connects dataset steps 1 and 2. '
                    'Segments repeat the connecting dataset; full path counts are separate. Rows summed across paths are not unique-edge counts.'),
                ('Evidence', 'Verified/inferred/unknown are stored classifications, not execution proof. '
                    + ('Offline citations included; raw source text ' + ('included.' if include_source_text else 'excluded.')
                       if include_evidence else 'Evidence sheet excluded; citations cannot be inspected offline.')),
                *[('Warning', warning) for warning in warnings]]
            first = sheet_table('Lineage Paths', headers, path_rows, scope_rows)
            first.activate()
            first.set_first_sheet()
            sheet_table('Lineage Steps', STEP_HEADERS, step_rows)
            if include_evidence:
                sheet_table('Evidence', EVIDENCE_HEADERS + (['Source excerpt'] if include_source_text else []), evidence_rows)
        if len(output.getbuffer()) > MAX_WORKBOOK_BYTES:
            raise ValueError('Workbook exceeds 64 MiB; narrow the selection')
        if time.monotonic() - started > MAX_SECONDS:
            raise ValueError('Workbook time limit exceeded; narrow the selection and retry')
    return output.getvalue(), metadata
