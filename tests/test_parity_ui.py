from pathlib import Path

from streamlit.testing.v1 import AppTest

from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


def test_identical_asset_labels_have_independent_workspace_widgets(tmp_path, monkeypatch):
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    store = Store(tmp_path)
    ids = [store.create_workspace(name) for name in ('SQL', 'SAS')]
    for w in ids:
        Importer(store, w).files([('a.sql', b'create table pub.all_kpis as select id from raw.a;')], {'.sql'})
        analyze(store, w)
    store.close()
    app = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    app.switch_page('ui/pages/explorer.py').run()
    choose = next(c for c in app.selectbox if c.label == 'Choose an exact asset')
    first_key = choose.key
    choose.select('pub.all_kpis  [table]').run()
    app.selectbox(key='workspace').set_value(ids[1]).run()
    choose = next(c for c in app.selectbox if c.label == 'Choose an exact asset')
    assert choose.key != first_key
    assert choose.value is None
    choose.select('pub.all_kpis  [table]').run()
    assert not app.exception and any(s.label == 'Traversal depth' for s in app.slider)
