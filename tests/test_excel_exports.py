"""Workbook semantics and inert OOXML content, read independently of the writer."""
import io
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pytest

from dataforge import exports
from dataforge.graph import LineageGraph

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def cells(data: Any, sheet: Any=1) -> tuple[Any, ...]:
    """Handle cells for the test scenario.

    Args:
        data: Data value used by the test case.
        sheet: Sheet value used by the test case.

    Returns:
        Value produced for the test scenario.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root = ET.fromstring(archive.read(f'xl/worksheets/sheet{sheet}.xml'))
        shared = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            shared = [''.join(n.itertext()) for n in ET.fromstring(archive.read('xl/sharedStrings.xml'))]
        rows = []
        for row in root.findall('.//m:sheetData/m:row', NS):
            values = []
            for cell in row.findall('m:c', NS):
                value = cell.find('m:v', NS)
                text = ''.join(t.text or '' for t in cell.findall('.//m:t', NS))
                values.append(shared[int(value.text)] if cell.get('t') == 's' else
                              text if cell.get('t') == 'inlineStr' else
                              float(value.text) if value is not None else '')
            rows.append(values)
        return root, rows


def table(data: Any, sheet: Any=1) -> Any:
    """Handle table for the test scenario.

    Args:
        data: Data value used by the test case.
        sheet: Sheet value used by the test case.

    Returns:
        Value produced for the test scenario.
    """
    _, rows = cells(data, sheet)
    header = next(i for i, row in enumerate(rows) if row and row[0] in {'Path ID', 'Evidence ID'})
    return [dict(zip(rows[header], row)) for row in rows[header + 1:]]


def graph(names: Any, pairs: Any) -> Any:
    """Provide the graph fixture used by the tests.

    Args:
        names: Names value used by the test case.
        pairs: Pairs value used by the test case.

    Returns:
        Value produced for the test scenario.
    """
    return LineageGraph([{'asset_id': n, 'name': n, 'kind': 'table'} for n in names], [
        {'edge_id': f'E{i}', 'source_id': s, 'target_id': t, 'kind': 'select',
         'status': 'verified', 'confidence': .9, 'source_hash': 'abc', 'file_id': 'file',
         'relative_path': 'job.sql', 'statement_id': f'S{i}', 'start_line': 2, 'end_line': 4}
        for i, (s, t) in enumerate(pairs)])


def workbook(g: Any, selected: Any, direction: str='upstream', **kwargs: Any) -> Any:
    """Handle workbook for the test scenario.

    Args:
        g: G value used by the test case.
        selected: Selected value used by the test case.
        direction: Direction value used by the test case.
        kwargs: Keyword arguments forwarded to the operation.

    Returns:
        Value produced for the test scenario.
    """
    report = g.path_report(selected, direction, depth=30)
    return exports.lineage_xlsx(report, g.nodes, {'workspace': 'Demo', 'revision': 'rev1',
        'selected_asset': selected, 'export_time': '2026-10-18T12:00:00+05:30'}, **kwargs)


def test_branched_workbook_keeps_job_identity_and_distinct_citations() -> None:
    g = graph(['orders', 'customers', 'report'], [('orders', 'report'), ('customers', 'report'),
                                               ('orders', 'report')])
    g.nodes['orders'].update(name='work.stage', metadata={'job_id': 'one'})
    g.nodes['customers'].update(name='work.stage', metadata={'job_id': 'two'})
    citation = g.graph['customers']['report']['evidence'][0]
    citation.pop('confidence')
    citation['status'] = 'inferred'
    data, metadata = workbook(g, 'report', include_evidence=True)
    assert metadata['relationship_count'] == 2
    steps = table(data, 2)
    assert len(table(data)) == 2 and len(steps) == 2
    assert {s['Source dataset'] for s in steps} == {'work.stage [job: one]', 'work.stage [job: two]'}
    by_id = {s['Source asset ID']: s for s in steps}
    assert by_id['orders']['Evidence count'] == 2
    assert by_id['customers']['Evidence count'] == 1
    assert by_id['customers']['Confidence'] == '' and by_id['customers']['Evidence status'] == 'inferred'
    evidence = table(data, 3)
    assert len(evidence) == 3 and {r['Evidence ID'] for r in evidence} == {'E0', 'E1', 'E2'}
    assert {r['Source content hash'] for r in evidence} == {'abc'}


def test_imported_names_are_literal_text_without_formulas_or_external_links() -> None:
    labels = ['=SUM(1,2)', '+cmd', '-1', '@name', 'https://example.org', '日本語_数据']
    data, _ = workbook(graph([*labels, 'target'], [(label, 'target') for label in labels]), 'target')
    assert {row['Step 1 - Starting dataset'] for row in table(data)} == set(labels)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert not any('externalLink' in name or 'vbaProject' in name for name in archive.namelist())
        for name in archive.namelist():
            if name.startswith('xl/worksheets/') and name.endswith('.xml'):
                root = ET.fromstring(archive.read(name))
                assert root.find('.//m:f', NS) is None and root.find('.//m:hyperlink', NS) is None


def test_timeout_during_streaming_closes_and_removes_temporary_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that timeout during streaming closes and removes temporary output.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    import dataforge.excel_exports as excel

    ticks = iter([0] * 15 + [100] * 100)
    monkeypatch.setattr(excel.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(excel.tempfile, 'tempdir', str(tmp_path))
    with pytest.raises(ValueError, match='time limit'):
        workbook(graph(['a', 'b'], [('a', 'b')]), 'b')
    assert list(tmp_path.iterdir()) == []


def test_dense_branches_stop_at_global_relationship_budget_with_visible_omissions() -> None:
    """Verify that dense branches stop at global relationship budget with visible omissions."""
    names = ['selected'] + [f'L{level}_{n}' for level in range(7) for n in range(6)]
    pairs = [(f'L0_{n}', 'selected') for n in range(6)]
    pairs += [(f'L{level}_{s}', f'L{level - 1}_{t}') for level in range(1, 7)
              for s in range(6) for t in range(6)]
    g = graph(names, pairs)
    report = g.path_report('selected', limit=500, depth=30, max_relationships=10, max_evidence=100)
    data, metadata = exports.lineage_xlsx(report, g.nodes, {'revision': 'dense'})
    assert report['truncated'] and not metadata['complete']
    assert metadata['relationship_count'] == 10
    assert any('omitted' in r['Notes'] for r in table(data))
    assert any('Relationship limit' in r['Coverage'] for r in table(data))
