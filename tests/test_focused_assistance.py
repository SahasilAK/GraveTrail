"""Focused discovery is source backed, selection bounded and explicitly accepted."""
import json
from zipfile import ZipFile

import httpx
import pytest
from test_assistance_queue import queued as queued_fixture

from dataforge.assistance_queue import request_review
from dataforge.ingestion import Importer
from dataforge.llm import assist_task, merge_claims
from dataforge.model_capabilities import ModelCapabilities, bind_capabilities
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


@pytest.mark.parametrize('entry', ['manual', 'review'])
@pytest.mark.parametrize('coordinates', [(10, 11), (6, 7)])
def test_mysql_missing_target_and_coordinate_correction(queued, entry, coordinates):
    store, w, _ = queued
    source, code = fixture_source(store, w)
    result = send(store, w, source, {'claims': [claim(code, *coordinates)]}, entry)
    assert result['outcome'] == 'validated', result
    details = json.loads(store.rows('SELECT details FROM llm_records WHERE record_id=?', [result['record_id']])[0]['details'])
    assert details['selection'] == {'first': 1, 'last': 13}
    assert result['result']['claims'][0]['start_line'] == 10
    assert bool(details['grounding']['corrections']) == (coordinates == (6, 7))
    assert any(r['name'] == claim(code)['target'] and r['action'] == 'create' for r in details['grounding']['resources'])
    assert not [e for e in store.edges(w) if e['method'] == 'llm']
    assert merge_claims(store, w, result['record_id']) == 1
    assert merge_claims(store, w, result['record_id']) == 1
    for _ in range(2):
        analyze(store, w)
        edges = [e for e in store.edges(w) if e['method'] == 'llm']
        assert len(edges) == 1 and edges[0]['status'] == 'inferred'
        inferred = next(a for a in store.assets(w) if a['name'] == claim(code)['target'])
        assert json.loads(inferred['metadata'])['origin'] == 'ai_inferred'
        assert not any('funding_deals' in a['name'] for a in store.assets(w))


@pytest.mark.parametrize('update,reason', [
    ({'source': 'core.treasury_funding_deals_current'}, 'unsupported_relationship'),
    ({'target': 'vendor_mysql.fabricated'}, 'unsupported_relationship'),
    ({'operation': 'DELETE'}, 'unsupported_relationship'),
    ({'source': 'vendor_mysql.treasury_treasury_positions_004',
      'target': 'core.treasury_treasury_positions_current'}, 'unsupported_relationship'),
])
def test_unproved_claims_have_safe_actionable_reasons(queued, update, reason):
    store, w, _ = queued
    source, code = fixture_source(store, w)
    result = send(store, w, source, {'claims': [claim(code, **update)]})
    assert result['outcome'] == 'quarantined'
    assert result['failure']['code'] == reason
    assert 'quote' not in result['failure']


def test_rebinding_stays_inside_selection_and_rejects_ambiguity(queued):
    store, w, _ = queued
    source, code = fixture_source(store, w)
    result = send(store, w, source, {'claims': [claim(code, 6, 7)]}, first=1, last=9)
    assert result['failure']['code'] == 'evidence_not_found'
    doubled = code + '\n' + '\n'.join(code.splitlines()[9:11])
    Importer(store, w).files([(PATH, doubled.encode())], {'.sql'})
    source = store.file(source['file_id'])
    result = send(store, w, source, {'claims': [claim(code, 6, 7)]}, last=len(doubled.splitlines()))
    assert result['failure']['code'] == 'ambiguous_evidence'


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


def test_manual_uses_confirmed_budget_and_redacted_preview(queued):
    from dataforge.llm import Profile, preview_assistance
    store, w, _ = queued
    source, code = fixture_source(store, w)
    p = Profile.model_validate_json(store.rows('SELECT config FROM llm_profiles')[0]['config'])
    p.output_mode = 'automatic'
    p.model_capabilities = bind_capabilities(ModelCapabilities(context_tokens=107520, source='manual'), p)
    store.execute('UPDATE llm_profiles SET config=?', [p.model_dump_json()])
    before = store.rows('SELECT * FROM llm_records')
    preview = preview_assistance(store, w, source['file_id'], 1, 13, 'sql_lineage')
    assert store.rows('SELECT * FROM llm_records') == before
    result = send(store, w, source, {'claims': [claim(code)]})
    assert result['budget'] == preview['budget']
    assert preview['budget']['reserved_output'] == 30643


@pytest.mark.parametrize('code,source,target,operation', [
    ('-- INSERT INTO mart.x SELECT * FROM raw.a;\nSELECT 1;', 'raw.a', 'mart.x', 'INSERT'),
    ("SELECT 'INSERT INTO mart.x SELECT * FROM raw.a;';", 'raw.a', 'mart.x', 'INSERT'),
    ('WITH a AS (SELECT * FROM raw.real) INSERT INTO mart.x SELECT * FROM a;', 'a', 'mart.x', 'INSERT'),
    ('data work.x; set &runtime; run;', 'raw.a', 'work.x', 'DATA'),
    ('create table mart.x as select * from raw.a; create table mart.y as select * from raw.b;', 'raw.a', 'mart.y', 'CREATE'),
])
def test_executable_roles_are_independent_of_quote_matching(queued, code, source, target, operation):
    store, w, _ = queued
    ext = '.sas' if operation == 'DATA' else '.sql'
    Importer(store, w).files([('bad' + ext, code.encode())], {ext})
    src = next(f for f in store.files(w) if f['relative_path'] == 'bad' + ext)
    payload = {'claims': [{**claim(''), 'source': source, 'target': target, 'operation': operation,
                          'quote': code, 'start_line': 1, 'end_line': len(code.splitlines())}]}
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={
        'choices': [{'message': {'content': json.dumps(payload)}}]}))
    result = assist_task(store, w, src['file_id'], 1, len(code.splitlines()),
                         'sas_lineage' if ext == '.sas' else 'sql_lineage', transport=transport)
    assert result['outcome'] == 'quarantined'
    assert result['failure']['code'] == 'unsupported_relationship'


def test_exact_coordinates_disambiguate_repeated_quotes(queued):
    store, w, _ = queued
    source, code = fixture_source(store, w)
    doubled = code + '\n' + '\n'.join(code.splitlines()[9:11])
    Importer(store, w).files([(PATH, doubled.encode())], {'.sql'})
    source = store.file(source['file_id'])
    result = send(store, w, source, {'claims': [claim(code)]}, last=len(doubled.splitlines()))
    assert result['outcome'] == 'validated'


@pytest.mark.parametrize('conflict', ['duplicate', 'unresolved', 'unqualified'])
def test_catalog_conflicts_do_not_become_new_resources(queued, conflict):
    store, w, _ = queued
    source, code = fixture_source(store, w)
    name = claim(code)['target']
    if conflict == 'unqualified':
        code = code.replace(name, 'treasury_treasury_positions_004')
        Importer(store, w).files([(PATH, code.encode())], {'.sql'})
        source = store.file(source['file_id'])
        store.execute('INSERT INTO assets VALUES (?,?,?,?,?,?,?)', ['conflict', w, name, name, 'table', False, '{}'])
    else:
        for index in range(2 if conflict == 'duplicate' else 1):
            store.execute('INSERT INTO assets VALUES (?,?,?,?,?,?,?)', [str(index), w, name, name,
                'unresolved' if conflict == 'unresolved' else 'table', False, '{}'])
    result = send(store, w, source, {'claims': [claim(code, target='treasury_treasury_positions_004' if conflict == 'unqualified' else name)]})
    assert result['outcome'] == 'quarantined'
    assert result['failure']['code'] == 'ambiguous_identity'


def test_sas_new_work_resources_preserve_job_and_provenance(queued):
    store, w, _ = queued
    store.set_setting(w, 'job_by_folder', {'one/': 'one', 'two/': 'two'})
    code = 'data work.new; set raw.a; run;'
    Importer(store, w).files([('one/new.sas', code.encode()), ('two/new.sas', code.encode())], {'.sas'})
    records = []
    for source in [f for f in store.files(w) if f['extension'] == '.sas']:
        payload = {'claims': [{**claim(''), 'source': 'raw.a', 'target': 'work.new', 'operation': 'DATA',
                              'start_line': 1, 'end_line': 1, 'quote': code}]}
        result = assist_task(store, w, source['file_id'], 1, 1, 'sas_lineage', transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(payload)}}]})))
        assert result['outcome'] == 'validated', result
        merge_claims(store, w, result['record_id'])
        records.append(result['record_id'])
    analyze(store, w)
    assets = [a for a in store.assets(w) if a['name'] == 'work.new']
    assert len(assets) == 2 and all(a['temporary'] for a in assets)
    assert {json.loads(a['metadata'])['job_id'] for a in assets} == {'one', 'two'}
    assert len([e for e in store.edges(w) if e['method'] == 'llm']) == 2


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
    source, code = fixture_source(store, w)
    for _ in range(2):
        result = send(store, w, source, {'claims': [claim(code)]})
        merge_claims(store, w, result['record_id'])
    assert len([e for e in store.edges(w) if e['method'] == 'llm']) == 1
    analyze(store, w)
    assert len([e for e in store.edges(w) if e['method'] == 'llm']) == 1


def test_legacy_result_without_selection_remains_safely_mergeable(queued):
    store, w, _ = queued
    source, code = fixture_source(store, w)
    result = send(store, w, source, {'claims': [claim(code)]})
    row = store.rows('SELECT details FROM llm_records WHERE record_id=?', [result['record_id']])[0]
    details = json.loads(row['details'])
    for field in ['selection', 'grounding', 'settings', 'failure']:
        details.pop(field, None)
    details['schema_version'] = '1'
    store.execute('UPDATE llm_records SET details=? WHERE record_id=?', [json.dumps(details), result['record_id']])
    assert merge_claims(store, w, result['record_id']) == 1
    analyze(store, w)
    assert len([e for e in store.edges(w) if e['method'] == 'llm']) == 1


@pytest.mark.parametrize('panel', ['assistance', 'unresolved_review'])
def test_mysql_through_both_diagnostics_panels(queued, monkeypatch, panel):
    from streamlit.testing.v1 import AppTest

    store, w, _ = queued
    source, code = fixture_source(store, w)
    calls = []
    def provider(self, system, user, **kwargs):
        calls.append(kwargs['prepared_request'][1])
        return '```json\n' + json.dumps({'claims': [claim(code, 6, 7)]}) + '\n```', {}
    monkeypatch.setattr('dataforge.llm.Adapter.complete', provider)
    script = (f'from dataforge.store import Store\nfrom ui.{panel} import render\n'
              f'store = Store({str(store.home)!r})\ntry:\n    render(store, {w!r})\nfinally:\n    store.close()')
    view = AppTest.from_string(script, default_timeout=30).run()
    if panel == 'assistance':
        next(s for s in view.selectbox if s.label == 'File for assistance').set_value(source['file_id']).run()
        next(s for s in view.selectbox if s.label == 'Analysis task').set_value('sql_lineage').run()
        first_label, last_label, request_label = 'Evidence start line', 'Evidence end line', 'Analyze selected evidence with AI'
    else:
        diagnostic = store.rows('SELECT diagnostic_id FROM diagnostics WHERE file_id=?', [source['file_id']])[0]
        next(s for s in view.selectbox if s.label == 'Diagnostic to review').set_value(diagnostic['diagnostic_id']).run()
        first_label, last_label, request_label = 'Review start line', 'Review end line', 'Request AI review of this range'
    next(n for n in view.number_input if n.label == first_label).set_value(1).run()
    next(n for n in view.number_input if n.label == last_label).set_value(13).run()
    assert not calls and not view.exception
    next(b for b in view.button if b.label == request_label).click().run()
    assert not view.exception and len(calls) == 1, [e.value for e in [*view.error, *view.warning]]
    assert any('coordinates corrected' in i.value for i in view.info)
    assert any('resource proposals' in str(x.value) for x in view.markdown)
    assert not [e for e in store.edges(w) if e['method'] == 'llm']
    next(b for b in view.button if b.label == 'Merge grounded relationships as inferred').click().run()
    assert not view.exception
    assert len([e for e in store.edges(w) if e['method'] == 'llm']) == 1


@pytest.mark.parametrize('operation', ['ai_request', 'review_request'])
def test_mysql_through_shared_service_entry_points(queued, operation):
    from dataforge.agent.contracts import AccessPolicy
    from dataforge.agent.service import AgentService

    store, w, _ = queued
    source, code = fixture_source(store, w)
    service = AgentService(store, AccessPolicy(allow_write=True, allow_llm=True,
        allowed_llm_origins=('http://localhost:20128',)))
    service.provider_transport = httpx.MockTransport(lambda r: httpx.Response(200, json={
        'choices': [{'message': {'content': json.dumps({'claims': [claim(code, 6, 7)]})}}]}))
    try:
        common = dict(first=1, last=13, expected_hash=source['content_hash'])
        if operation == 'review_request':
            diagnostic = store.rows('SELECT diagnostic_id FROM diagnostics WHERE file_id=?', [source['file_id']])[0]
            common['diagnostic_id'] = diagnostic['diagnostic_id']
        else:
            common.update(file_id=source['file_id'], task='sql_lineage')
        result = service.call(operation, w, **common)
        assert result['outcome'] == 'validated'
        accepted = service.call('ai_merge', w, record_id=result['record_id'])
        assert accepted['merged'] == 1 and not accepted['refresh_required']
    finally:
        service.close()


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


def test_case_sensitive_resources_cannot_share_a_binding(queued):
    store, w, _ = queued
    store.set_setting(w, 'case_sensitive', True)
    code = 'CREATE TABLE mart.x AS SELECT * FROM raw.A JOIN raw.a ON 1=1;'
    Importer(store, w).files([('case.sql', code.encode())], {'.sql'})
    source = next(f for f in store.files(w) if f['relative_path'] == 'case.sql')
    claims = [{**claim(''), 'source': name, 'target': 'mart.x', 'operation': 'CREATE',
               'quote': code, 'start_line': 1, 'end_line': 1} for name in ['raw.A', 'raw.a']]
    result = assist_task(store, w, source['file_id'], 1, 1, 'sql_lineage', transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'claims': claims})}}]})))
    assert result['outcome'] == 'validated', result
    assert merge_claims(store, w, result['record_id']) == 2
    edges = [e for e in store.edges(w) if e['method'] == 'llm']
    assert len({e['source_id'] for e in edges}) == 2
    analyze(store, w)
    assert len({e['source_id'] for e in store.edges(w) if e['method'] == 'llm'}) == 2


@pytest.mark.parametrize('extension,dialect,code,line,quote,operation,target', [
    ('.sql', 'postgres', '/* outer\n/* nested */\nINSERT INTO mart.x SELECT * FROM raw.a;\n*/\nSELECT 1;',
     3, 'INSERT INTO mart.x SELECT * FROM raw.a;', 'INSERT', 'mart.x'),
    ('.sas', '', '%macro generate;\ndata work.x; set raw.a; run;\n%mend;',
     2, 'data work.x; set raw.a; run;', 'DATA', 'work.x'),
    ('.sql', 'postgres', 'INSERT INTO mart.x /* outer\n/* nested */\nINSERT INTO mart.x SELECT * FROM raw.a;\n*/ SELECT * FROM raw.a;',
     3, 'INSERT INTO mart.x SELECT * FROM raw.a;', 'INSERT', 'mart.x'),
    ('.sas', '', 'data work.y;\nmessage = "\ndata work.x; set raw.a; run;\n";\nset raw.a;\nrun;',
     3, 'data work.x; set raw.a; run;', 'DATA', 'work.x'),
    ('.sas', '', 'data work.x;\n* comment\ndata work.x;\nset raw.a; run;',
     3, 'data work.x;', 'DATA', 'work.x'),
])
def test_selection_retains_original_comment_and_macro_context(queued, extension, dialect, code, line, quote, operation, target):
    store, w, _ = queued
    store.set_setting(w, 'dialect', dialect)
    Importer(store, w).files([('context' + extension, code.encode())], {extension})
    source = next(f for f in store.files(w) if f['relative_path'] == 'context' + extension)
    payload = {'claims': [{**claim(''), 'source': 'raw.a', 'target': target, 'operation': operation,
                          'quote': quote, 'start_line': line, 'end_line': line}]}
    result = assist_task(store, w, source['file_id'], line, line,
        'sas_lineage' if extension == '.sas' else 'sql_lineage', transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(payload)}}]})))
    assert result['outcome'] == 'quarantined'


@pytest.mark.parametrize('lexical', [True, False])
def test_sas_implicit_work_and_configured_library_identities(queued, lexical):
    store, w, _ = queued
    store.set_setting(w, 'library_mappings', {'inlib': 'core'})
    code = 'data new; set inlib.a; run;'
    Importer(store, w).files([('mapped.sas', code.encode())], {'.sas'})
    source = next(f for f in store.files(w) if f['relative_path'] == 'mapped.sas')
    payload = {'claims': [{**claim(''), 'source': 'inlib.a' if lexical else 'core.a',
        'target': 'new' if lexical else 'work.new', 'operation': 'DATA', 'quote': code,
        'start_line': 1, 'end_line': 1}]}
    result = assist_task(store, w, source['file_id'], 1, 1, 'sas_lineage', transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(payload)}}]})))
    assert result['outcome'] == 'validated', result
    merge_claims(store, w, result['record_id'])
    analyze(store, w)
    assets = {a['asset_id']: a for a in store.assets(w)}
    edge = next(e for e in store.edges(w) if e['method'] == 'llm')
    assert assets[edge['source_id']]['name'] == 'core.a'
    assert assets[edge['target_id']]['name'] == 'work.new'
    assert assets[edge['target_id']]['temporary']


def test_unrelated_parser_options_do_not_erase_accepted_ai(queued):
    store, w, _ = queued
    code = 'CREATE TABLE mart.new AS SELECT * FROM raw.a;'
    Importer(store, w).files([('new.sql', code.encode())], {'.sql'})
    source = next(f for f in store.files(w) if f['relative_path'] == 'new.sql')
    payload = {'claims': [{**claim(''), 'source': 'raw.a', 'target': 'mart.new',
        'operation': 'CREATE', 'quote': code, 'start_line': 1, 'end_line': 1}]}
    result = send(store, w, source, payload, last=1)
    merge_claims(store, w, result['record_id'])
    store.set_setting(w, 'csv_sample_rows', 0)
    store.set_setting(w, 'dialect_by_folder', {'unrelated/': 'postgres'})
    analyze(store, w)
    assert len([e for e in store.edges(w) if e['method'] == 'llm']) == 1


def test_line_coordinates_must_disambiguate_repeated_quotes(queued):
    store, w, _ = queued
    quote = 'INSERT INTO mart.x SELECT * FROM raw.a;'
    code = quote + ' ' + quote
    Importer(store, w).files([('repeat.sql', code.encode())], {'.sql'})
    source = next(f for f in store.files(w) if f['relative_path'] == 'repeat.sql')
    result = send(store, w, source, {'claims': [{**claim(''), 'source': 'raw.a', 'target': 'mart.x',
        'quote': quote, 'start_line': 1, 'end_line': 1}]}, last=1)
    assert result['outcome'] == 'quarantined'
    assert result['failure']['code'] == 'ambiguous_evidence'


def test_sas_mapping_does_not_apply_twice_to_saved_host_identity(queued):
    from dataforge.focused_grounding import ground_response
    from dataforge.llm import GroundedResponse
    code = 'data work.new; set inlib.a; run;'
    source = {'raw_content': code, 'extension': '.sas'}
    settings = {'library_mappings': {'inlib': 'core', 'core': 'other'}}
    response = GroundedResponse.model_validate({'claims': [{**claim(''), 'source': 'inlib.a',
        'target': 'work.new', 'operation': 'DATA', 'quote': code, 'start_line': 1, 'end_line': 1}]})
    ground_response(response, source, 1, 1, settings)
    assert response.claims[0].source == 'core.a'
    ground_response(response, source, 1, 1, settings, rebind=False)


def test_persistent_declaration_cannot_reuse_a_temporary_identity(queued):
    store, w, _ = queued
    code = 'CREATE TABLE stage AS SELECT * FROM raw.a;'
    Importer(store, w).files([('conflict.sql', code.encode())], {'.sql'})
    source = next(f for f in store.files(w) if f['relative_path'] == 'conflict.sql')
    store.execute('INSERT INTO assets VALUES (?,?,?,?,?,?,?)', ['temporary', w, 'stage', 'stage', 'table', True, '{}'])
    result = send(store, w, source, {'claims': [{**claim(''), 'source': 'raw.a', 'target': 'stage',
        'operation': 'CREATE', 'quote': code, 'start_line': 1, 'end_line': 1}]}, last=1)
    assert result['outcome'] == 'quarantined'
    assert result['failure']['code'] == 'ambiguous_identity'


def test_static_refresh_without_accepted_assistance_skips_identity_replay(queued, monkeypatch):
    from dataforge.configuration import ParsingSettings
    from dataforge.services import restore_manual_ai_results
    store, w, _ = queued
    monkeypatch.setattr('dataforge.services.AssetResolver', lambda *a, **k: pytest.fail('No accepted AI identities to replay'))
    restore_manual_ai_results(store, w, [], ParsingSettings().model_dump())


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


def test_unified_dispatch_preserves_sql_sas_source_eligibility(queued):
    from dataforge.focused_grounding import ground_response
    from dataforge.llm import GroundedResponse
    store, w, _ = queued
    Importer(store, w).files([('data.csv', b'INSERT INTO mart.x SELECT * FROM raw.a;')], {'.csv'})
    source = next(f for f in store.files(w) if f['extension'] == '.csv')
    with pytest.raises(ValueError, match='SQL/SAS'):
        assist_task(store, w, source['file_id'], 1, 1, 'sql_lineage',
                    transport=httpx.MockTransport(lambda r: pytest.fail('CSV must not be treated as executable source')))
    with pytest.raises(ValueError, match='executable'):
        ground_response(GroundedResponse(), store.file(source['file_id']), 1, 1, {})
