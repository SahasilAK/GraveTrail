"""Focused discovery is source backed, selection bounded and explicitly accepted."""
import json
from zipfile import ZipFile

import httpx
import pytest
from test_assistance_queue import queued as queued_fixture

from dataforge.assistance_queue import request_review
from dataforge.ingestion import Importer
from dataforge.llm import assist_task, merge_claims
from dataforge.services import analyze

queued = queued_fixture

PATH = '09_vendor_dialects/mysql/mysql_004_treasury_treasury_positions.sql'


def fixture_source(store, w):
    with ZipFile('tests/sample_data/banking_legacy_sql_2114_lineage_stress_test.zip') as archive:
        code = archive.read(PATH).decode()
    Importer(store, w).files([(PATH, code.encode())], {'.sql'})
    analyze(store, w)
    source = next(f for f in store.files(w) if f['relative_path'] == PATH)
    return source, code


def claim(code, first=10, last=11, **updates):
    return {'source': 'core.treasury_treasury_positions_current',
            'target': 'vendor_mysql.treasury_treasury_positions_004', 'operation': 'INSERT',
            'start_line': first, 'end_line': last, 'quote': '\n'.join(code.splitlines()[9:11]),
            'confidence': .99, 'explanation': 'Explicit read and write', **updates}


def send(store, w, source, payload, entry='manual', first=1, last=13):
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={
        'choices': [{'message': {'content': '```json\n' + json.dumps(payload) + '\n```'}}]}))
    if entry == 'review':
        diagnostic = store.rows('SELECT diagnostic_id FROM diagnostics WHERE file_id=?', [source['file_id']])[0]
        return request_review(store, w, diagnostic['diagnostic_id'], source['content_hash'], first, last,
                              transport=transport)
    return assist_task(store, w, source['file_id'], first, last, 'sql_lineage',
                       expected_hash=source['content_hash'], transport=transport)


def test_merge_is_atomic_and_source_job_pinned(queued, monkeypatch):
    store, w, _ = queued
    source, code = fixture_source(store, w)
    result = send(store, w, source, {'claims': [claim(code)]})
    before = store.assets(w)
    execute = store.execute
    def fail(sql, params=None):
        if sql.startswith('INSERT INTO edges'):
            raise RuntimeError('synthetic write failure')
        return execute(sql, params)
    with monkeypatch.context() as patch:
        patch.setattr(store, 'execute', fail)
        with pytest.raises(RuntimeError):
            merge_claims(store, w, result['record_id'])
    assert store.assets(w) == before
    assert not [e for e in store.edges(w) if e['method'] == 'llm']
    store.set_setting(w, 'default_job', 'changed')
    with pytest.raises(ValueError, match='job|session'):
        merge_claims(store, w, result['record_id'])


def test_stale_source_identity_and_settings_block_acceptance(queued):
    store, w, _ = queued
    source, code = fixture_source(store, w)
    result = send(store, w, source, {'claims': [claim(code)]})
    store.set_setting(w, 'case_sensitive', True)
    with pytest.raises(ValueError, match='settings'):
        merge_claims(store, w, result['record_id'])
    store.set_setting(w, 'case_sensitive', False)
    Importer(store, w).files([(PATH, (code + '\nSELECT 1;').encode())], {'.sql'})
    with pytest.raises(ValueError, match='Source changed'):
        merge_claims(store, w, result['record_id'])


def test_separate_submissions_do_not_duplicate_accepted_lineage(queued):
    store, w, _ = queued
    code = 'CREATE TABLE mart.new AS SELECT * FROM raw.a;'
    Importer(store, w).files([('new.sql', code.encode())], {'.sql'})
    source = next(file for file in store.files(w) if file['relative_path'] == 'new.sql')
    payload = {'claims': [{**claim(''), 'source': 'raw.a', 'target': 'mart.new',
        'operation': 'CREATE', 'quote': code, 'start_line': 1, 'end_line': 1}]}
    for _ in range(2):
        result = send(store, w, source, payload, last=1)
        merge_claims(store, w, result['record_id'])
    assert len([e for e in store.edges(w) if e['method'] == 'llm']) == 1
    store.set_setting(w, 'csv_sample_rows', 0)
    store.set_setting(w, 'dialect_by_folder', {'unrelated/': 'postgres'})
    analyze(store, w)
    assert len([e for e in store.edges(w) if e['method'] == 'llm']) == 1


def test_changed_prepared_request_cannot_dispatch_under_an_old_preview(queued):
    from dataforge.llm import preview_assistance
    store, w, _ = queued
    source, _ = fixture_source(store, w)
    preview = preview_assistance(store, w, source['file_id'], 1, 13, 'sql_lineage')
    store.set_setting(w, 'dialect', 'mysql')
    with pytest.raises(ValueError, match='preview|preparation'):
        assist_task(store, w, source['file_id'], 1, 13, 'sql_lineage',
                    expected_request=preview['request_fingerprint'],
                    transport=httpx.MockTransport(lambda r: pytest.fail('stale preview must not send')))


def test_quote_itself_must_support_the_claimed_read_and_write_roles(queued):
    store, w, _ = queued
    quote = 'SELECT * FROM raw.a JOIN mart.x ON 1=1'
    code = 'CREATE TABLE mart.x AS ' + quote + ';'
    Importer(store, w).files([('roles.sql', code.encode())], {'.sql'})
    source = next(f for f in store.files(w) if f['relative_path'] == 'roles.sql')
    result = send(store, w, source, {'claims': [{**claim(''), 'source': 'raw.a', 'target': 'mart.x',
        'operation': 'CREATE', 'quote': quote, 'start_line': 1, 'end_line': 1}]}, last=1)
    assert result['outcome'] == 'quarantined'
    assert result['failure']['code'] == 'unsupported_relationship'
