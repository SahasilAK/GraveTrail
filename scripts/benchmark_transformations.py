"""Reproducible synthetic column-traversal measurement in a disposable data home."""
import json
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store
from dataforge.transformations import trace_columns


def benchmark(home, stages=120, width=20):
    store = Store(home)
    try:
        workspace = store.create_workspace('Column transformation review')
        code = '\n'.join(
            f'CREATE TABLE stage_{stage} AS SELECT ' + ', '.join(
                f'c{column} + c{(column + 1) % width} AS c{column}' for column in range(width))
            + f' FROM {"raw_input" if stage == 0 else f"stage_{stage - 1}"};'
            for stage in range(stages))
        Importer(store, workspace).files([('column_chain.sql', code.encode()), ('order_totals.sql', b'''
CREATE TABLE mart.order_totals AS
SELECT o.order_id, o.quantity * o.unit_price AS gross_amount,
       COALESCE(d.discount_amount, 0) AS discount_amount, 42 AS constant_value
FROM raw.orders o LEFT JOIN raw.discounts d ON o.order_id=d.order_id
WHERE o.status='COMPLETE';
''')], {'.sql'})
        start = time.perf_counter()
        analyze(store, workspace)
        analysis_seconds = time.perf_counter() - start
        target = next(a['asset_id'] for a in store.assets(workspace) if a['name'] == f'stage_{stages - 1}')
        tracemalloc.start()
        start = time.perf_counter()
        trace = trace_columns(store, workspace, target, 'c0', depth=30, limit=200)
        query_seconds = time.perf_counter() - start
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return {'home': str(store.home), 'workspace_id': workspace, 'stages': stages, 'columns_per_stage': width,
                'stored_derivations': store.rows('SELECT count(*) AS n FROM column_derivations')[0]['n'],
                'analysis_seconds': round(analysis_seconds, 4), 'query_seconds': round(query_seconds, 4),
                'query_python_peak_bytes': peak, 'returned_derivations': len(trace['derivations']),
                'returned_path_steps': len(trace['paths']), 'truncated': trace['truncated'],
                'coverage_reasons': sorted({c['reason'] for c in trace['coverage']}),
                'measurement': 'Synthetic fixture; tracemalloc measures Python allocations, excluding DuckDB native memory'}
    finally:
        store.close()


if __name__ == '__main__':
    if len(sys.argv) > 1:
        print(json.dumps(benchmark(Path(sys.argv[1])), indent=2))
    else:
        with tempfile.TemporaryDirectory(prefix='gravetrail-column-benchmark-') as directory:
            print(json.dumps(benchmark(Path(directory)), indent=2))
