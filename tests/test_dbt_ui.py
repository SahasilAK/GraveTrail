from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_sources_exposes_dbt_mode_and_preserves_legacy_import(tmp_path, monkeypatch):
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    app = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    app.switch_page('ui/pages/builder.py').run()
    kind = next((s for s in app.selectbox if s.label == 'Project type'), None)
    assert kind is not None
    kind.set_value('dbt project').run()
    assert not app.exception
    assert any('dbt' in c.value.lower() for c in app.caption)
    assert any(s.label == 'dbt analysis mode' for s in app.selectbox)


def test_populated_dbt_resource_inspector_renders_and_selects_macro(tmp_path, monkeypatch):
    from dataforge.ingestion import Importer
    from dataforge.services import analyze
    from dataforge.store import Store
    store = Store(tmp_path)
    w = store.create_workspace('dbt UI')
    Importer(store, w).files([('dbt_project.yml', b'name: shop'), ('models/a.sql', b'select 1 as id'),
        ('macros/money.sql', b'{% macro money(x) %}{{x}}/100{% endmacro %}')], set(), source_kind='dbt')
    analyze(store, w)
    store.close()
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    app = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    app.switch_page('ui/pages/explorer.py').run()
    assert not app.exception
    assert any(s.label == 'dbt resource' for s in app.selectbox)


def test_dbt_inspector_can_reach_resources_after_the_first_page(tmp_path, monkeypatch):
    from contextlib import closing

    from dataforge.ingestion import Importer
    from dataforge.services import analyze
    from dataforge.store import Store
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('paged dbt')
        Importer(store, w).files([('dbt_project.yml', b'name: shop'),
            *[(f'models/m{i:03d}.sql', b'select 1 as id') for i in range(101)]], set(), source_kind='dbt')
        analyze(store, w)
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    app = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    app.switch_page('ui/pages/explorer.py').run()
    next(b for b in app.button if b.label == 'Next dbt resources').click().run()
    assert not app.exception
    resource = next(s for s in app.selectbox if s.label == 'dbt resource')
    assert any('m100' in option for option in resource.options)
