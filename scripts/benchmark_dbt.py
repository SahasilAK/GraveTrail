"""Measure synthetic dbt project cold/warm/invalidation analysis in a disposable home.

Run: uv run python scripts/benchmark_dbt.py --models 1000
Memory is tracemalloc's Python-allocation peak, not total process/DuckDB memory.
"""
import argparse
import json
import platform
import tempfile
import time
import tracemalloc
from contextlib import closing

from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', type=int, default=1000)
    args = parser.parse_args()
    if not 1 <= args.models <= 10000:
        parser.error('--models must be between 1 and 10000')
    entries = [('dbt_project.yml', b'name: benchmark'),
        ('macros/pass.sql', b'{% macro pass_value(x) %}{{ x }}{% endmacro %}')]
    for index in range(args.models):
        query = 'select 1 as id' if index == 0 else (
            "select id from {{ ref('model_%04d') }}" % (index - 1))
        if index > 2 and index % 10 == 0:
            query += " union all select id from {{ ref('model_0000') }}"
        if index % 20 == 1:
            query = query.replace('select id', "select {{ pass_value('id') }} as id", 1)
        entries.append((f'models/model_{index:04d}.sql', query.encode()))
    entries.append(('models/properties.yml', ('models:\n' + ''.join(
        f'  - name: model_{index:04d}\n    columns: [{{name: id}}]\n' for index in range(args.models))).encode()))
    with tempfile.TemporaryDirectory(prefix='gravetrail-dbt-benchmark-') as directory, closing(Store(directory)) as store:
        workspace = store.create_workspace('benchmark')
        importer = Importer(store, workspace)
        importer.files(entries, set(), source_kind='dbt')
        measurements = []
        tracemalloc.start()
        for phase in ('cold', 'warm', 'model_edit'):
            if phase == 'model_edit':
                importer.files([('dbt_project.yml', entries[0][1]),
                                ('models/model_0000.sql', b'select 2 as id')], set(), source_kind='dbt')
            started = time.perf_counter()
            result = analyze(store, workspace)
            measurements.append({'phase': phase, 'seconds': round(time.perf_counter() - started, 3),
                                 'result': result})
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        print(json.dumps({'platform': platform.platform(), 'python': platform.python_version(),
            'models': args.models, 'python_peak_mib': round(peak / 1024 ** 2, 2),
            'resources': store.rows('SELECT count(*) AS n FROM dbt_resources')[0]['n'],
            'measurements': measurements}, default=str, indent=2))


if __name__ == '__main__':
    main()
