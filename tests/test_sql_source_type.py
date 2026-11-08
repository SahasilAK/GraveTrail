import asyncio
import io
import zipfile
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from dataforge import services
from dataforge.agent.contracts import AccessPolicy
from dataforge.agent.mcp_server import create_server
from dataforge.agent.service import AgentService
from dataforge.ai_analysis_store import load_accepted_file_results, save_run
from dataforge.ai_context import prepare_analysis
from dataforge.cli import app as cli
from dataforge.configuration import ParsingSettings
from dataforge.ingestion import Importer
from dataforge.store import Store

DATABRICKS = b"create table mart.databricks_orders as select id from raw.`order items`;"
SQL_SERVER = b"select top 5 id into mart.legacy from raw.[legacy orders];"


def test_file_choice_and_legacy_folder_rule_publish_after_reopen(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace("Mixed SQL engines")
    store.set_setting(w, 'dialect_by_folder', {'legacy/': 'tsql'})
    importer = Importer(store, w)
    importer.files([('legacy/report.sql', SQL_SERVER)], {'.sql'})
    importer.files([('databricks.sql', DATABRICKS)], {'.sql'}, sql_dialect='databricks')
    store.close()

    store = Store(tmp_path)
    try:
        assert services.analyze(store, w)['edges'] == 2
        assert {a['name'] for a in store.assets(w)} == {
            'mart.databricks_orders', 'raw.order items', 'mart.legacy', 'raw.legacy orders'}
        assert services.analysis_is_current(store, w)
        source = next(f for f in store.files(w) if f['relative_path'] == 'databricks.sql')
        assert services.source_dialect(source, ParsingSettings().model_dump()) == 'databricks'
    finally:
        store.close()


def test_explicit_generic_in_zip_overrides_folder_for_sql_members_only(tmp_path):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as zipped:
        zipped.writestr('jobs/a.sql', DATABRICKS)
        zipped.writestr('jobs/b.SQL', 'create table mart.standard as select id from raw.standard;')
        zipped.writestr('jobs/step.sas', 'proc sql; select id from raw.source; quit;')
        zipped.writestr('jobs/data.csv', 'id\n1\n')
    store = Store(tmp_path)
    try:
        w = store.create_workspace('Mixed ZIP')
        config = ParsingSettings(dialect='tsql', dialect_by_extension={'.sql': 'postgres'},
                                 dialect_by_folder={'jobs/': 'databricks'}).model_dump()
        for key in ('dialect', 'dialect_by_extension', 'dialect_by_folder'):
            store.set_setting(w, key, config[key])
        importer = Importer(store, w)
        with pytest.raises(ValueError, match='Unknown SQL dialect'):
            importer.zip(archive.getvalue(), {'.sql', '.sas', '.csv'}, sql_dialect='unknown')
        assert not store.files(w)
        assert importer.zip(archive.getvalue(), {'.sql', '.sas', '.csv'}, sql_dialect='').accepted == 4
        files = {f['relative_path']: f for f in store.files(w)}
        assert services.source_dialect(files['jobs/a.sql'], config) == ''
        assert services.source_dialect(files['jobs/b.SQL'], config) == ''
        assert services.source_dialect(files['jobs/step.sas'], config) == 'databricks'
        services.analyze(store, w)
        assert 'mart.standard' in {a['name'] for a in store.assets(w)}
        assert 'mart.databricks_orders' not in {a['name'] for a in store.assets(w)}
        assert services.source_dialect(store.file(files['jobs/a.sql']['file_id']), config) == ''
        importer.zip(archive.getvalue(), {'.sql', '.sas', '.csv'})
        services.analyze(store, w)
        assert 'mart.databricks_orders' in {a['name'] for a in store.assets(w)}
    finally:
        store.close()


def test_same_bytes_reimport_invalidates_both_table_and_column_facts(tmp_path, monkeypatch):
    store = Store(tmp_path)
    try:
        w = store.create_workspace('Dialect changes')
        importer = Importer(store, w)
        importer.files([('orders.sql', DATABRICKS)], {'.sql'}, sql_dialect='databricks')
        assert services.analyze(store, w)['edges'] == 1
        assert store.rows('SELECT * FROM column_derivations WHERE workspace_id=?', [w])
        assert services.analysis_is_current(store, w)
        with monkeypatch.context() as version:
            version.setattr(services, 'PARSER_VERSION', 'future')
            assert not services.analysis_is_current(store, w)

        importer.files([('orders.sql', DATABRICKS)], {'.sql'}, sql_dialect='')
        assert not services.analysis_is_current(store, w)
        assert services.analyze(store, w)['analyzed'] == 1
        assert not store.edges(w)
        assert not store.rows('SELECT * FROM column_derivations WHERE workspace_id=?', [w])
        assert services.analysis_is_current(store, w)
    finally:
        store.close()


def test_same_bytes_reimport_during_analysis_cannot_publish_old_dialect(tmp_path):
    store = Store(tmp_path)
    try:
        w = store.create_workspace('Concurrent dialect change')
        importer = Importer(store, w)
        importer.files([('orders.sql', DATABRICKS)], {'.sql'}, sql_dialect='databricks')
        assert services.analyze(store, w)['edges'] == 1

        def reimport(*_):
            importer.files([('orders.sql', DATABRICKS)], {'.sql'}, sql_dialect='')

        with pytest.raises(ValueError, match='Inventory changed during analysis'):
            services.analyze(store, w, progress=reimport)
        assert len(store.edges(w)) == 1
        assert not services.analysis_is_current(store, w)
        assert services.analyze(store, w)['edges'] == 0
    finally:
        store.close()


def test_ai_checkpoint_and_accepted_facts_invalidate_on_dialect_change(tmp_path, monkeypatch):
    store = Store(tmp_path)
    try:
        w = store.create_workspace('AI dialect invalidation')
        importer = Importer(store, w)
        importer.files([('orders.sql', DATABRICKS)], {'.sql'}, sql_dialect='databricks')
        prepared = prepare_analysis(store, w, {'mode': 'hybrid'})
        assert prepared.sources[0].dialect == 'databricks'
        results, config, _ = services.prepare_analysis_results(store, w)
        fid = results[0][0]['file_id']
        save_run(store, w, 'accepted', mode='hybrid', status='committed',
                 configuration=config, accepted_results=results)
        assert fid in load_accepted_file_results(store, w, config)
        with monkeypatch.context() as version:
            version.setattr(services, 'PARSER_VERSION', 'future')
            assert fid not in load_accepted_file_results(store, w, config)

        services.set_source_dialect(store, w, fid, '')
        store.set_setting(w, 'dialect_by_folder', {'orders': 'databricks'})
        corrected = prepare_analysis(store, w, {'mode': 'hybrid'})
        assert corrected.manifest_hash != prepared.manifest_hash
        assert corrected.sources[0].dialect == ''
        assert fid not in load_accepted_file_results(store, w, config)
        assert services.analyze(store, w)['edges'] == 0
    finally:
        store.close()


def test_builder_sql_selector_and_inventory_correction(tmp_path, monkeypatch):
    inputs = tmp_path / 'inputs'
    inputs.mkdir()
    (inputs / 'orders.sql').write_bytes(DATABRICKS)
    (inputs / 'rows.csv').write_text('id\n1\n', encoding='utf-8')
    (inputs / 'notes.txt').write_text('Not a source file', encoding='utf-8')
    home = tmp_path / 'home'
    monkeypatch.setenv('DATAFORGE_HOME', str(home))
    monkeypatch.setenv('DATAFORGE_ALLOWED_ROOTS', str(inputs))
    view = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    w = view.session_state['workspace']
    view.switch_page('ui/pages/builder.py').run()
    types = next(el for el in view.multiselect if el.label == 'File types to analyze')
    types.set_value(['csv']).run()
    assert all(el.label != 'SQL source type' for el in view.selectbox)
    next(el for el in view.multiselect if el.label == types.label).set_value(['sql', 'csv']).run()
    selector = next(el for el in view.selectbox if el.label == 'SQL source type')
    assert selector.value == 'Use workspace settings'
    assert {'Use workspace settings', 'Generic SQL', 'Databricks', 'SQL Server'} <= set(selector.options)
    selector.set_value('Databricks')
    next(el for el in view.segmented_control if el.label == 'Input source').set_value('Host directory').run()
    next(el for el in view.text_input if el.label == 'Directory on application host').set_value(str(inputs))
    next(el for el in view.button if el.label == 'Import into inventory').click().run()
    assert any(s.label == 'Import complete. 2 files ready for Analysis.' and s.state == 'complete'
               for s in view.status)
    assert any(p.label.startswith('Skipped files (1)') for p in view.expander)
    assert any('notes.txt: Unsupported file type' in el.value for el in view.text)
    next(el for el in view.button if el.label == 'Continue to Analysis').click().run()
    assert any(el.label == 'Analyze all files' for el in view.button)
    view.switch_page('ui/pages/builder.py').run()
    next(el for el in view.segmented_control if el.label == 'Source workspace').set_value('Inventory').run()
    inventory = view.dataframe[0].value.set_index('relative_path')
    assert inventory.loc['orders.sql', 'sql_source_type'] == 'Databricks'
    assert not inventory.loc['rows.csv', 'sql_source_type']

    store = Store(home)
    try:
        assert services.analyze(store, w)['edges'] == 1
        view.session_state['inventory_source_panel'] = True
        view.run()
        next(el for el in view.selectbox if el.label == 'SQL source type').set_value('Generic SQL').run()
        next(el for el in view.button if el.label == 'Save SQL source type').click().run()
        assert not view.exception
        assert view.dataframe[0].value.set_index('relative_path').loc['orders.sql', 'sql_source_type'] == 'Generic SQL'
        assert not services.analysis_is_current(store, w)
        assert services.analyze(store, w)['edges'] == 0
    finally:
        store.close()


def test_cli_and_mcp_accept_optional_sql_dialect(tmp_path):
    inputs = tmp_path / 'inputs'
    inputs.mkdir()
    (inputs / 'orders.sql').write_bytes(DATABRICKS)
    home = tmp_path / 'home'
    store = Store(home)
    w = store.create_workspace('CLI and MCP')
    store.set_setting(w, 'dialect', 'databricks')
    store.close()

    imported = CliRunner().invoke(cli, ['--home', str(home), '--json', '--allow-write', '--allowed-root',
        str(inputs), 'ingest', str(inputs), '-w', w, '--sql-dialect', ''])
    assert imported.exit_code == 0, imported.stdout
    store = Store(home)
    service = AgentService(store, AccessPolicy(allow_write=True, import_roots=(str(inputs),)))
    server = create_server(service)

    async def check():
        result = await server.call_tool('ingest_sources', {'workspace_id': w, 'path': str(inputs),
            'extensions': ['sql'], 'sql_dialect': 'databricks'})
        assert not result.isError, result.structuredContent
        return result.structuredContent['job_id']

    try:
        assert services.analyze(store, w)['edges'] == 0
        job_id = asyncio.run(check())
        job = service.jobs.wait(job_id, w)
        assert job['status'] == 'completed', job
        assert services.analyze(store, w)['edges'] == 1
    finally:
        service.close()
        store.close()
