"""Exercise cleanup through the real application and disposable storage homes."""
import json
import os
import time
from contextlib import closing
from pathlib import Path

import duckdb
import pytest
from streamlit.testing.v1 import AppTest

from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


@pytest.fixture
def cleanup_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('test')
        Importer(store, workspace).files([
            ('a.sql', b'CREATE TABLE b AS SELECT id FROM a;'),
            ('b.sql', b'CREATE TABLE c AS SELECT id FROM b;'),
        ], {'.sql'})
        analyze(store, workspace)
    app = AppTest.from_file(Path('app.py').resolve(), default_timeout=30).run()
    app.switch_page('ui/pages/management.py').run()
    app.segmented_control[0].set_value('Cleanup & recovery').run()
    assert not app.exception
    from ui.common import get_store
    store = get_store(str(tmp_path))
    try:
        yield app, store, workspace
    finally:
        store.close()
        get_store.clear(str(tmp_path))


def choose_category(app, category):
    next(s for s in app.selectbox if s.label == 'Cleanup category').set_value(category).run()


def preview_and_confirm(app, phrase='test'):
    next(b for b in app.button if b.label == 'Preview cleanup').click().run()
    assert not app.exception
    next(t for t in app.text_input if t.label == 'Type ' + phrase + ' to confirm').set_value(phrase).run()


@pytest.mark.parametrize('category,other_workspace', [
    ('workspace', False), ('workspace', True), ('application', False), ('application', True),
])
def test_delete_workspace_or_reset_application_can_continue(cleanup_app, category, other_workspace):
    app, store, workspace = cleanup_app
    other = store.create_workspace('other') if other_workspace else None
    app.run()
    choose_category(app, category)
    preview_and_confirm(app, 'RESET GRAVETRAIL' if category == 'application' else 'test')
    next(b for b in app.button if b.label == 'Apply previewed cleanup').click().run()
    assert not app.exception
    remaining = {row['workspace_id'] for row in store.workspaces()}
    assert workspace not in remaining
    assert app.session_state['workspace'] in remaining
    if other and category == 'workspace':
        assert remaining == {other}
    assert list((store.home / 'backups').glob('*.zip'))
    app.switch_page('ui/pages/dashboard.py').run()
    assert not app.exception


def test_changed_source_selection_requires_new_preview_and_confirmation(cleanup_app):
    app, store, workspace = cleanup_app
    choices = next(s for s in app.multiselect if s.label.startswith('Imported files to delete'))
    files = [row['file_id'] for row in store.files(workspace)]
    choices.set_value([files[0]]).run()
    preview_and_confirm(app)
    assert not next(b for b in app.button if b.label == 'Apply previewed cleanup').disabled
    next(s for s in app.multiselect if s.label.startswith('Imported files to delete')).set_value([files[1]]).run()
    assert not any(b.label == 'Apply previewed cleanup' and not b.disabled for b in app.button)
    next(b for b in app.button if b.label == 'Preview cleanup').click().run()
    assert next(b for b in app.button if b.label == 'Apply previewed cleanup').disabled
    assert len(store.files(workspace)) == 2


def test_cleanup_metrics_handle_unsafe_job_paths_without_crashing(cleanup_app, tmp_path):
    app, store, workspace = cleanup_app
    jobs = store.home / 'agent' / 'jobs'
    jobs.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / 'outside.json'
    outside.write_text('{}')
    os.link(outside, jobs / ('a' * 32 + '.json'))
    app.run()
    assert not app.exception
    assert app.error
    assert len(store.files(workspace)) == 2
    assert outside.read_text() == '{}'


@pytest.mark.parametrize('body', ['{}', '[]', '{"workspace_id": 12, "status": "running", "updated_at": "bad"}'])
def test_malformed_job_journal_refuses_cleanup_without_crashing(cleanup_app, body):
    app, store, workspace = cleanup_app
    jobs = store.home / 'agent' / 'jobs'
    jobs.mkdir(parents=True, exist_ok=True)
    journal = jobs / ('a' * 32 + '.json')
    journal.write_text(body)
    app.run()
    assert not app.exception
    assert app.error
    assert journal.read_text() == body
    assert len(store.files(workspace)) == 2


def test_workspace_delete_database_failure_is_reported_and_rolled_back(cleanup_app, monkeypatch):
    app, store, workspace = cleanup_app
    choose_category(app, 'workspace')
    preview_and_confirm(app)
    execute = store.execute

    def fail_delete(sql, params=None):
        if sql == 'DELETE FROM workspaces WHERE workspace_id=?':
            raise duckdb.IOException('Injected database write failure')
        return execute(sql, params)

    monkeypatch.setattr(store, 'execute', fail_delete)
    next(b for b in app.button if b.label == 'Apply previewed cleanup').click().run()
    assert not app.exception
    assert app.error
    assert len(store.files(workspace)) == 2
    assert store.edges(workspace)
    assert list((store.home / 'backups').glob('*.zip'))


def test_cleanup_refreshes_counts_and_requires_fresh_confirmation(cleanup_app):
    app, store, workspace = cleanup_app
    choose_category(app, 'lineage')
    preview_and_confirm(app)
    next(b for b in app.button if b.label == 'Apply previewed cleanup').click().run()
    assert not app.exception
    assert not store.edges(workspace)
    rows = app.dataframe[0].value
    assert rows.loc[rows['Category'] == 'lineage', 'Records affected'].iloc[0] == 0
    assert app.success
    next(b for b in app.button if b.label == 'Preview cleanup').click().run()
    assert next(b for b in app.button if b.label == 'Apply previewed cleanup').disabled


def test_automatic_staging_cleanup_does_not_invalidate_new_preview(cleanup_app):
    app, store, workspace = cleanup_app
    store.set_setting(workspace, 'auto_cleanup_temporary', True)
    app.run()
    directory = store.home / 'history-recovery' / workspace
    directory.mkdir(parents=True, exist_ok=True)
    stale = directory / ('a' * 32 + '.tmp')
    stale.write_bytes(b'recovery staging')
    os.utime(stale, (time.time() - 90000,) * 2)
    choose_category(app, 'lineage')
    # A new stale file can appear between interactions, e.g. a failed archival write.
    stale.write_bytes(b'new staging')
    os.utime(stale, (time.time() - 90000,) * 2)
    preview_and_confirm(app)
    next(b for b in app.button if b.label == 'Apply previewed cleanup').click().run()
    assert not app.exception
    assert not app.error
    assert not store.edges(workspace)


def test_disabling_automatic_cleanup_preserves_staging_files(cleanup_app):
    app, store, workspace = cleanup_app
    store.set_setting(workspace, 'auto_cleanup_temporary', True)
    app.run()
    directory = store.home / 'history-recovery' / workspace
    directory.mkdir(parents=True, exist_ok=True)
    stale = directory / ('a' * 32 + '.tmp')
    stale.write_bytes(b'keep staging')
    os.utime(stale, (time.time() - 90000,) * 2)
    next(c for c in app.checkbox if c.label.startswith('Automatically clear expired')).uncheck()
    next(b for b in app.button if b.label == 'Save temporary cleanup preference').click().run()
    assert not app.exception
    assert not store.setting(workspace, 'auto_cleanup_temporary')
    assert stale.read_bytes() == b'keep staging'
    assert not store.rows('SELECT 1 FROM temporary_recovery WHERE workspace_id=?', [workspace])


def test_history_selection_requires_new_preview(cleanup_app):
    app, store, workspace = cleanup_app
    choose_category(app, 'history')
    preview_and_confirm(app)
    run = store.runs(workspace)[0]['run_id']
    next(s for s in app.selectbox if s.label == 'Specific analysis run (optional)').set_value(run).run()
    assert not any(b.label == 'Apply previewed cleanup' and not b.disabled for b in app.button)


def test_workspace_cleanup_service_rejects_invalid_job_journal(tmp_path):
    from dataforge.cleanup import apply_cleanup, cleanup_plan

    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('test')
        preview = cleanup_plan(store, workspace, 'workspace')
        jobs = store.home / 'agent' / 'jobs'
        jobs.mkdir(parents=True, exist_ok=True)
        (jobs / ('a' * 32 + '.json')).write_text(json.dumps({'status': 'completed'}))
        with pytest.raises(ValueError, match='[Jj]ob journal'):
            apply_cleanup(store, preview, 'test')
        assert store.workspaces()


def test_column_cleanup_preserves_table_lineage_support(tmp_path):
    from dataforge.ai_analysis_store import save_claim_decisions, save_run
    from dataforge.cleanup import apply_cleanup, cleanup_plan
    from dataforge.database_maintenance import inspect_database

    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('test')
        Importer(store, workspace).files([('a.sql', b'CREATE TABLE b AS SELECT id FROM a;')], {'.sql'})
        analyze(store, workspace)
        save_run(store, workspace, 'ai-run', mode='ai', status='committed')
        edge_id = store.edges(workspace)[0]['edge_id']
        usage_id = store.rows('SELECT usage_id FROM column_usages WHERE workspace_id=?', [workspace])[0]['usage_id']
        derivation_id = store.rows('SELECT derivation_id FROM column_derivations WHERE workspace_id=?', [workspace])[0]['derivation_id']
        save_claim_decisions(store, workspace, 'ai-run', [], supports=[
            {'fact_type': 'edge', 'fact_id': edge_id},
            {'fact_type': 'usage', 'fact_id': usage_id},
            {'fact_type': 'derivation', 'fact_id': derivation_id},
        ])
        preview = cleanup_plan(store, workspace, 'columns')
        assert preview['records']['analysis_fact_support'] == 2
        apply_cleanup(store, preview, 'test')
        assert store.edges(workspace)[0]['edge_id'] == edge_id
        supports = store.rows('SELECT fact_type,fact_id FROM analysis_fact_support WHERE workspace_id=?', [workspace])
        assert supports == [{'fact_type': 'edge', 'fact_id': edge_id}]
        assert not store.rows('SELECT 1 FROM column_usages WHERE workspace_id=?', [workspace])
        assert not store.rows('SELECT 1 FROM column_derivations WHERE workspace_id=?', [workspace])
        assert inspect_database(store)['ok']
