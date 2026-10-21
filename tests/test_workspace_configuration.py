import json
from pathlib import Path
from typing import Any

import pytest

from dataforge.store import Store


def test_workspace_edit_preserves_identity_inventory_and_other_workspaces(tmp_path: Path) -> None:
    """Verify that workspace edit preserves identity inventory and other workspaces.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.ingestion import Importer

    store = Store(tmp_path)
    try:
        first = store.create_workspace("Before", "Old description")
        other = store.create_workspace("Other")
        Importer(store, first).files([("q.sql", b"select id from raw.a;")], {".sql"})
        store.update_workspace(first, "  After  ", "New description")
        row = next(w for w in store.workspaces() if w["workspace_id"] == first)
        assert (row["name"], row["description"]) == ("After", "New description")
        assert len(store.files(first)) == 1
        assert next(w for w in store.workspaces() if w["workspace_id"] == other)["name"] == "Other"
        for name, description in [(" ", ""), ("a" * 201, ""), ("Valid", "x" * 2001)]:
            with pytest.raises(ValueError):
                store.update_workspace(first, name, description)
        with pytest.raises(ValueError, match="exist"):
            store.update_workspace("missing", "Valid", "")
    finally:
        store.close()
    reopened = Store(tmp_path)
    try:
        assert next(w for w in reopened.workspaces() if w["workspace_id"] == first)["name"] == "After"
    finally:
        reopened.close()


def test_safe_configuration_round_trip_preserves_supported_settings(tmp_path: Path) -> None:
    """Verify that safe configuration round trip preserves supported settings.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.configuration import export_workspace_configuration, import_workspace_configuration

    store = Store(tmp_path)
    try:
        original = store.create_workspace("Portable", "Description")
        values = {"dialect": "snowflake", "dialect_by_folder": {"jobs/": "tsql"},
                  "macros": {"year": "2026"}, "case_sensitive": True, "max_file_mb": 42,
                  "max_files": 90, "parse_workers": 3, "graph_limit": 60, "traversal_depth": 9,
                  "tree_expansion_depth": 2, "graph_direction": "combined", "collapse_temporary": False,
                  "graph_labels": "full", "graph_palette": "neutral", "graph_edge_width": 4,
                  "source_view_mode": "relevant", "source_line_numbers": False,
                  "llm_concurrency": 2, "llm_chunk_chars": 1500}
        for k, v in values.items():
            store.set_setting(original, k, v)
        store.set_setting(original, "external_llm", True)
        store.set_setting(original, "allow_full_source", True)
        store.set_setting(original, "default_profile", "private-profile")
        store.set_setting(original, "unrecognized_secret", "DO_NOT_EXPORT")
        payload = export_workspace_configuration(store, original)
        assert "DO_NOT_EXPORT" not in payload and "private-profile" not in payload
        assert "external_llm" not in payload and "allow_full_source" not in payload
        copied = import_workspace_configuration(store, payload)
        assert copied != original
        assert next(w for w in store.workspaces() if w["workspace_id"] == copied)["description"] == "Description"
        assert {k: store.setting(copied, k) for k in values} == values
        assert store.setting(copied, "external_llm", False) is False
        assert not store.files(copied)
    finally:
        store.close()


@pytest.mark.parametrize("settings", [{"parse_workers": 99}, {"case_sensitive": "false"},
                                     {"graph_limit": -1}, {"base_url": "https://example.com"},
                                     {"external_llm": True}, {"dialect": "invented"},
                                     {"graph_direction": "sideways"}, {"graph_labels": "script"},
                                     {"graph_palette": "#bad"}, {"graph_edge_width": 99},
                                     {"collapse_temporary": "false"}, {"source_line_numbers": 1},
                                     {"source_view_mode": "execute"}, {"llm_concurrency": 0},
                                     {"llm_concurrency": 5}, {"llm_chunk_chars": 499}])
def test_invalid_configuration_cannot_create_a_partial_workspace(tmp_path: Path, settings: dict[str, Any]) -> None:
    """Verify that invalid configuration cannot create a partial workspace.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        settings: Settings values supplied to the test case.
    """
    from dataforge.configuration import import_workspace_configuration

    store = Store(tmp_path)
    try:
        with pytest.raises(ValueError):
            import_workspace_configuration(store, json.dumps({"format": "dataforge-metadata-v2",
                "name": "Bad", "description": "", "settings": settings}))
        assert store.workspaces() == []
    finally:
        store.close()


def test_v1_configuration_ignores_legacy_private_settings(tmp_path: Path) -> None:
    """Verify that v1 configuration ignores legacy private settings.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.configuration import import_workspace_configuration

    store = Store(tmp_path)
    try:
        wid = import_workspace_configuration(store, json.dumps({"format": "dataforge-metadata-v1",
            "name": "Legacy", "settings": {"dialect": "postgres", "parse_workers": 2,
            "llm_history": True, "external_llm": True, "default_profile": "old"}}))
        assert store.setting(wid, "dialect") == "postgres"
        assert store.setting(wid, "parse_workers") == 2
        assert store.setting(wid, "llm_history", False) is False
        assert store.setting(wid, "default_profile", "") == ""
    finally:
        store.close()


def test_configuration_creation_rolls_back_after_storage_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that configuration creation rolls back after storage failure.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.

    Raises:
        RuntimeError: Raised by the test helper.
    """
    from dataforge.configuration import import_workspace_configuration

    store = Store(tmp_path)
    try:
        def fail_setting(*args: Any) -> None:
            """Handle fail setting for the test scenario.

            Args:
                args: Positional arguments forwarded to the operation.

            Raises:
                RuntimeError: Raised by the test helper.
            """
            raise RuntimeError("Injected storage failure")
        monkeypatch.setattr(store, "set_setting", fail_setting)
        with pytest.raises(RuntimeError, match="Injected"):
            import_workspace_configuration(store, json.dumps({"format": "dataforge-metadata-v2", "name": "Atomic"}))
        assert store.workspaces() == []
    finally:
        store.close()
