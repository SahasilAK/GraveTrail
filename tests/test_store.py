from dataforge.store import Store


def test_workspace_settings_persist_and_isolate(tmp_path):
    store = Store(tmp_path)
    a = store.create_workspace("Alpha")
    b = store.create_workspace("Beta")
    store.set_setting(a, "dialect", "snowflake")
    assert store.setting(a, "dialect") == "snowflake"
    assert store.setting(b, "dialect", "") == ""
    store.close()
    reopened = Store(tmp_path)
    assert len(reopened.workspaces()) == 2
    assert reopened.setting(a, "dialect") == "snowflake"
    reopened.close()
