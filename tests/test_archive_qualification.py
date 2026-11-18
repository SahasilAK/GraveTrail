"""Archive gold is scorer-only; missing column labels never become an accuracy pass."""
import csv
import hashlib
import io
from zipfile import ZipFile

import pytest

from scripts.benchmark_lineage_archives import evaluate_archive, load_archive


def archive(tmp_path, *, corrupt=False):
    path = tmp_path / 'input.zip'
    code = '-- expected_inputs: fake.leak\nCREATE TABLE mart.b AS SELECT a.x FROM raw.a a;'
    def csv_text(fields, rows):
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        return stream.getvalue()
    with ZipFile(path, 'w') as zipped:
        zipped.writestr('query.sql', code)
        zipped.writestr('manifest/file_inventory.csv', csv_text(['path', 'sha256', 'dialect', 'scenario'], [{
            'path': 'query.sql', 'sha256': '0' * 64 if corrupt else hashlib.sha256(code.encode()).hexdigest(),
            'dialect': 'ansi', 'scenario': 'projection'}]))
        zipped.writestr('manifest/lineage_edges.csv', csv_text(['source_asset', 'target_asset', 'script_path'], [
            {'source_asset': 'raw.a', 'target_asset': 'mart.b', 'script_path': 'query.sql'}]))
    return path


def test_offline_scores_verified_archive_without_using_gold_as_source(tmp_path, monkeypatch):
    path = archive(tmp_path)
    cases, info = load_archive(path, 'sql', split='all')
    assert len(cases) == info['scripts'] == 1
    assert 'fake.leak' not in cases[0]['code']
    assert cases[0]['expected_edges'] == {('raw.a', 'mart.b')}
    assert cases[0]['dialect'] == ''
    monkeypatch.setattr('dataforge.llm.Adapter.complete', lambda *a, **k: pytest.fail('offline network'))
    report = evaluate_archive(path, 'sql', split='all')
    assert report['modes']['parser']['table_edges']['tp'] == 1
    assert report['modes']['parser']['table_edges']['precision'] == 1
    assert report['column_gold'] == 'unavailable'
    assert report['release_gate'] == 'insufficient_evidence'
    assert report['requests'] == 0
    with pytest.raises(ValueError, match='checksum'):
        load_archive(archive(tmp_path, corrupt=True), 'sql', split='all')


def test_live_comparison_requires_opt_in_and_retains_omissions(tmp_path, monkeypatch):
    path = archive(tmp_path)
    monkeypatch.delenv('DATAFORGE_AI_BENCHMARK_LIVE', raising=False)
    with pytest.raises(ValueError, match='opt-in'):
        evaluate_archive(path, 'sql', live=True, split='development')
    monkeypatch.setenv('DATAFORGE_AI_BENCHMARK_LIVE', '1')
    with pytest.raises(ValueError, match='split'):
        evaluate_archive(path, 'sql', live=True, split='all')
    monkeypatch.setattr('scripts.benchmark_lineage_archives.partition', lambda scenario: 'development')
    def failed(cases, **kwargs):
        assert 'fake.leak' not in cases[0]['code']
        assert kwargs['max_attempts'] == 1
        return {}, {'requests': 1, 'usage_known': False, 'input_tokens': None, 'output_tokens': None,
                    'failed_cases': 1, 'failures_by_case': {'query.sql': 'quarantined'}}
    monkeypatch.setattr('scripts.benchmark_lineage_archives._live_predictions', failed)
    report = evaluate_archive(path, 'sql', live=True, split='development', limit=1, max_attempts=1)
    assert report['modes']['ai']['table_edges']['fn'] == 1
    assert report['modes']['ai']['cases'][0]['failure'] == 'quarantined'
    assert set(report['modes']) == {'parser', 'ai'}
    assert report['modes']['ai']['table_edges']['precision'] is None
    assert report['release_gate'] == 'insufficient_evidence'
