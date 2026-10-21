import json
from contextlib import closing
from pathlib import Path

from dataforge.ingestion import Importer
from dataforge.reporting import validate_lineage_evidence
from dataforge.services import analyze
from dataforge.store import Store


def test_retail_zip_matches_independent_logical_edge_gold(tmp_path):
    root = Path(__file__).parent
    expected = json.loads((root / 'fixtures/dbt/gold.json').read_text())
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('Retail qualification')
        report = Importer(store, w).zip((root / 'sample_data/gravetrail_dbt_lineage_test_project.zip').read_bytes(),
                                       set(), source_kind='dbt')
        assert report.accepted >= 20
        analyze(store, w)
        assets = {a['asset_id']: a['name'] for a in store.assets(w)}
        pairs = {(assets[e['source_id']], assets[e['target_id']]) for e in store.edges(w)}
        assert pairs == {tuple(edge) for edge in expected['edges']}
        assert validate_lineage_evidence(store, w)['invalid_count'] == 0
        assert {r['resource_type'] for r in store.rows('SELECT resource_type FROM dbt_resources')} >= {
            'model', 'source', 'seed', 'snapshot', 'macro', 'test', 'unit_test', 'exposure', 'semantic_model'}
