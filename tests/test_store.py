from pathlib import Path

from dataforge.store import Store


def test_workspace_settings_persist_and_isolate(tmp_path: Path) -> None:
    """Verify that workspace settings persist and isolate.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
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
