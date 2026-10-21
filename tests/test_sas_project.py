import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from dataforge.agent.service import AgentService
from dataforge.graph import LineageGraph
from dataforge.ingestion import Importer
from dataforge.models import Diagnostic, ParseResult
from dataforge.services import analyze
from dataforge.store import Store


def test_sas_project_reaches_all_sources_with_exact_logical_edges_and_evidence(tmp_path: Path) -> None:
    """Verify that sas project reaches all sources with exact logical edges and evidence.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    archive = Path('tests/sample_data/dataforge_sas_lineage_test_project.zip')
    with ZipFile(archive) as zipped:
        name = next(n for n in zipped.namelist() if n.endswith('expected/lineage_manifest.json'))
        manifest = json.loads(zipped.read(name))
    store = Store(tmp_path)
    service = AgentService(store)
    try:
        w = store.create_workspace('SAS acceptance')
        assert Importer(store, w).zip(archive.read_bytes(), {'.sas'}).accepted == 86
        cold = analyze(store, w)
        graph = LineageGraph(store.assets(w), store.edges(w)).simplified()
        actual = {(graph.nodes[s]['name'], graph.nodes[t]['name']) for s, t in graph.graph.edges}
        expected = {(source, asset['target']) for asset in manifest['assets'] for source in asset['inputs']}
        assert actual == expected and len(actual) == 128
        assert sum(a['temporary'] for a in store.assets(w)) == 16
        upstream = service.call('lineage', w, asset='pub.all_kpis',
            options={'limit': 500, 'max_chars': 100000, 'max_depth': 30, 'collapse_temporary': True})
        names = {item['name'] for item in upstream['items']}
        assert {a['target'] for a in manifest['assets'] if a['stage'] == 'src'} <= names
        assert {n.split('.')[0] for n in names} | {'pub'} == {'src', 'ext', 'stg', 'core', 'mart', 'rpt', 'pub'}
        assert upstream['complete'] and upstream['analysis_current']
        for edge in store.edges(w):
            original = store.file(edge['file_id'])['raw_content']
            assert edge['code'] in original
            assert edge['code'] in '\n'.join(original.splitlines()[edge['start_line'] - 1:edge['end_line']])
            assert edge['method'] in {'sas-rules', 'sas-proc-sql'}
        assert not any(d['severity'] == 'error' for d in store.diagnostics(w))
        assert cold['analyzed'] == 86 and analyze(store, w)['cached'] == 86
    finally:
        service.close()
        store.close()


def test_parser_upgrade_replaces_old_failed_sas_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that parser upgrade replaces old failed sas cache.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    import dataforge.services as services

    store = Store(tmp_path)
    try:
        w = store.create_workspace('SAS cache upgrade')
        Importer(store, w).files([('q.sas', b'proc sql; create table mart.x as select id format=8. from raw.a; quit;')], {'.sas'})
        with monkeypatch.context() as old:
            old.setattr(services, 'PARSER_VERSION', '7')
            old.setattr(services, '_parse_inventory', lambda *args: ParseResult(diagnostics=[Diagnostic('Old parse failure', severity='error')]))
            analyze(store, w)
        assert not store.edges(w)
        upgraded = analyze(store, w)
        assert upgraded['analyzed'] == 1 and upgraded['cached'] == 0
        assert len(store.edges(w)) == 1
    finally:
        store.close()
