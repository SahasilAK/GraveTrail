"""Workbook semantics and inert OOXML content, read independently of the writer."""
import io
import zipfile
from xml.etree import ElementTree as ET

import pytest

from dataforge import exports
from dataforge.graph import LineageGraph

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def cells(data, sheet=1):
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


def table(data, sheet=1):
    _, rows = cells(data, sheet)
    header = next(i for i, row in enumerate(rows) if row and row[0] in {'Path ID', 'Evidence ID'})
    return [dict(zip(rows[header], row)) for row in rows[header + 1:]]


def graph(names, pairs):
    return LineageGraph([{'asset_id': n, 'name': n, 'kind': 'table'} for n in names], [
        {'edge_id': f'E{i}', 'source_id': s, 'target_id': t, 'kind': 'select',
         'status': 'verified', 'confidence': .9, 'source_hash': 'abc', 'file_id': 'file',
         'relative_path': 'job.sql', 'statement_id': f'S{i}', 'start_line': 2, 'end_line': 4}
        for i, (s, t) in enumerate(pairs)])


def workbook(g, selected, direction='upstream', **kwargs):
    report = g.path_report(selected, direction, depth=30)
    return exports.lineage_xlsx(report, g.nodes, {'workspace': 'Demo', 'revision': 'rev1',
        'selected_asset': selected, 'export_time': '2026-10-18T12:00:00+05:30'}, **kwargs)


def test_upstream_chain_is_source_to_target_with_typed_counts_and_filters():
    g = graph(['raw.orders', 'staging.clean', 'mart.sales'],
              [('raw.orders', 'staging.clean'), ('staging.clean', 'mart.sales')])
    data, metadata = workbook(g, 'mart.sales')
    path = table(data)[0]
    assert [path['Step 1 - Starting dataset'], path['Step 2'], path['Step 3']] == [
        'raw.orders', 'staging.clean', 'mart.sales']
    assert path['Dependency count'] == 2
    steps = table(data, 2)
    assert [(r['Relationship number'], r['Source dataset'], r['Target dataset']) for r in steps] == [
        (1, 'raw.orders', 'staging.clean'), (2, 'staging.clean', 'mart.sales')]
    assert metadata['path_count'] == 1 and metadata['relationship_count'] == 2
    root, rows = cells(data)
    assert 'Steps show data dependencies, not runtime execution order.' in str(rows)
    assert 'upstream' in str(rows)
    assert root.find('m:autoFilter', NS) is not None
    assert root.find('m:sheetViews/m:sheetView/m:pane', NS).get('state') == 'frozen'
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        book = ET.fromstring(archive.read('xl/workbook.xml'))
        assert [s.get('name') for s in book.find('m:sheets', NS)] == ['Lineage Paths', 'Lineage Steps']


def test_branches_and_multiple_citations_do_not_invent_relationships():
    g = graph(['orders', 'customers', 'report'], [('orders', 'report'), ('customers', 'report'),
                                               ('orders', 'report')])
    data, metadata = workbook(g, 'report', include_evidence=True)
    assert metadata['relationship_count'] == 2
    assert len(table(data)) == 2 and len(table(data, 2)) == 2
    assert sorted(r['Evidence count'] for r in table(data, 2)) == [1, 2]
    evidence = table(data, 3)
    assert len(evidence) == 3 and {r['Evidence ID'] for r in evidence} == {'E0', 'E1', 'E2'}
    assert {r['Source content hash'] for r in evidence} == {'abc'}


def test_wide_path_segments_overlap_and_steps_stay_unique():
    names = [f'dataset_{i}' for i in range(12)]
    data, metadata = workbook(graph(names, list(zip(names, names[1:]))), names[-1])
    paths = table(data)
    assert metadata['path_count'] == 1 and metadata['segment_count'] == 2
    assert [r['Segment'] for r in paths] == [1, 2]
    assert [r['Dataset step range'] for r in paths] == ['1–8', '8–12']
    assert paths[0]['Step 8'] == paths[1]['Step 1 - Starting dataset'] == 'dataset_7'
    assert [r['Relationship number'] for r in table(data, 2)] == list(range(1, 12))
    assert [r['Full path dependency count'] for r in paths] == [11, 11]


@pytest.mark.parametrize('label', ['=SUM(1,2)', '+cmd', '-1', '@name', 'https://example.org', '日本語_数据'])
def test_imported_names_are_literal_text_without_formulas_or_external_links(label):
    data, _ = workbook(graph([label, 'target'], [(label, 'target')]), 'target')
    assert table(data)[0]['Step 1 - Starting dataset'] == label
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert not any('externalLink' in name or 'vbaProject' in name for name in archive.namelist())
        for name in archive.namelist():
            if name.startswith('xl/worksheets/') and name.endswith('.xml'):
                root = ET.fromstring(archive.read(name))
                assert root.find('.//m:f', NS) is None and root.find('.//m:hyperlink', NS) is None


def test_isolated_and_cycle_paths_explain_coverage():
    data, _ = workbook(graph(['alone'], []), 'alone')
    assert table(data)[0]['Dependency count'] == 0
    assert 'known' in table(data)[0]['Coverage']
    cyclic, metadata = workbook(graph(['a', 'b'], [('a', 'b'), ('b', 'a')]), 'a')
    assert not metadata['complete'] and 'cycle' in table(cyclic)[0]['Coverage'].lower()


def test_empty_selection_and_oversized_cells_fail_explicitly():
    with pytest.raises(ValueError, match='Select'):
        workbook(graph([], []), 'missing')
    long_name = 'x' * 33000
    with pytest.raises(ValueError, match='cell|32767'):
        workbook(graph([long_name], []), long_name)


def test_path_report_bounds_relationships_before_materializing_and_retains_selection():
    g = graph(['a', 'b', 'c', 'd'], [('a', 'b'), ('b', 'c'), ('c', 'd')])
    upstream = g.path_report('d', depth=30, max_relationships=2)
    assert upstream['truncated'] and upstream['paths'][0]['nodes'] == ['b', 'c', 'd']
    assert upstream['paths'][0]['boundary'] == 'relationship_limit'
    downstream = g.path_report('a', 'downstream', depth=30, max_relationships=2)
    assert downstream['paths'][0]['nodes'] == ['a', 'b', 'c']
    with pytest.raises(ValueError, match='evidence'):
        g.path_report('d', max_evidence=1)


def test_collapsed_job_scoped_names_keep_identities_and_all_citations():
    g = graph(['a', 't', 'b'], [('a', 't'), ('t', 'b')])
    g.nodes['t'].update(name='work.stage', temporary=True, metadata={'job_id': 'job-a'})
    data, metadata = workbook(g.simplified(), 'b', include_evidence=True)
    steps = table(data, 2)
    assert metadata['relationship_count'] == 1 and metadata['evidence_count'] == 2
    assert 'work.stage' in steps[0]['Intermediate datasets']
    assert steps[0]['Temporary stages'] == 'Collapsed'
    assert (steps[0]['Source asset ID'], steps[0]['Target asset ID']) == ('a', 'b')


def test_collapsing_parallel_temporary_routes_preserves_separate_paths_and_bounds_evidence():
    g = graph(['a', 't1', 't2', 'b'], [('a', 't1'), ('t1', 'b'), ('a', 't2'), ('t2', 'b')])
    for node in ['t1', 't2']:
        g.nodes[node]['temporary'] = True
    collapsed = g.simplified(preserve_paths=True, evidence_limit=20)
    report = collapsed.path_report('b')
    assert len(report['paths']) == 2
    assert sorted(len(p['steps']) for p in report['paths']) == [1, 2]
    with pytest.raises(ValueError, match='evidence'):
        g.simplified(preserve_paths=True, evidence_limit=3)


def test_failed_writer_cleans_its_temporary_directory(tmp_path, monkeypatch):
    import dataforge.excel_exports as excel

    monkeypatch.setattr(excel.tempfile, 'tempdir', str(tmp_path))
    monkeypatch.setattr(excel, 'MAX_TEXT_BYTES', 100)
    with pytest.raises(ValueError, match='text limit'):
        workbook(graph(['a', 'b'], [('a', 'b')]), 'b')
    assert list(tmp_path.iterdir()) == []


def test_timeout_during_streaming_closes_and_removes_temporary_output(tmp_path, monkeypatch):
    import dataforge.excel_exports as excel

    ticks = iter([0] * 15 + [100] * 100)
    monkeypatch.setattr(excel.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(excel.tempfile, 'tempdir', str(tmp_path))
    with pytest.raises(ValueError, match='time limit'):
        workbook(graph(['a', 'b'], [('a', 'b')]), 'b')
    assert list(tmp_path.iterdir()) == []


def test_dense_branches_stop_at_global_relationship_budget_with_visible_omissions():
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


def test_repeated_job_names_remain_distinct_and_unknown_confidence_is_blank():
    g = graph(['left', 'right', 'target'], [('left', 'target'), ('right', 'target')])
    g.nodes['left'].update(name='work.stage', metadata={'job_id': 'one'})
    g.nodes['right'].update(name='work.stage', metadata={'job_id': 'two'})
    for _, _, attrs in g.graph.edges(data=True):
        attrs['evidence'][0].pop('confidence')
        attrs['evidence'][0]['status'] = 'inferred'
    data, _ = workbook(g, 'target')
    steps = table(data, 2)
    assert {s['Source dataset'] for s in steps} == {'work.stage [job: one]', 'work.stage [job: two]'}
    assert {s['Source asset ID'] for s in steps} == {'left', 'right'}
    assert all(s['Confidence'] == '' and s['Evidence status'] == 'inferred' for s in steps)
