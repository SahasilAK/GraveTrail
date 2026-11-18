
import pytest

from dataforge import services
from dataforge.ai_analysis_store import load_accepted_file_results, save_run
from dataforge.ai_context import prepare_analysis
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
