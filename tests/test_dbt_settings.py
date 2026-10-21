from contextlib import closing

import pytest

from dataforge.configuration import export_workspace_configuration, import_workspace_configuration
from dataforge.ingestion import Importer
from dataforge.services import analysis_is_current, analyze
from dataforge.settings_service import read_settings, save_ui_settings
from dataforge.store import Store


def test_dbt_settings_change_freshness_and_round_trip_portably(tmp_path):
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('settings')
        Importer(store, w).files([('dbt_project.yml', b'name: shop'),
            ('models/a.sql', b'select 1 as id')], set(), source_kind='dbt')
        analyze(store, w)
        assert analysis_is_current(store, w)
        save_ui_settings(store, w, 'dbt', {'dialect': 'postgres', 'public_vars': {'region': 'public'}})
        assert not analysis_is_current(store, w)
        assert analyze(store, w)['analyzed'] == 2
        assert analysis_is_current(store, w)
        new_w = import_workspace_configuration(store, export_workspace_configuration(store, w))
        assert read_settings(store, new_w, 'dbt')['values']['public_vars'] == {'region': 'public'}
        with pytest.raises(ValueError):
            from dataforge.dbt.models import DbtSettings
            DbtSettings(dialect='invalid-dialect')
