import threading
from pathlib import Path
from typing import Any

import httpx
import pytest
from focused_test_profiles import focused_profile


def test_chunks_preserve_complete_statements_and_original_coordinates() -> None:
    """Verify that chunks preserve complete statements and original coordinates."""
    from dataforge.llm_resources import context_chunks

    code = "-- preface\nselect 'semi;colon' from raw.a;\n\nselect id from raw.b;"
    chunks = context_chunks(code, ".sql", 1, 4, 50)
    assert [(c["first"], c["last"]) for c in chunks] == [(1, 2), (4, 4)]
    assert chunks[0]["code"] == code.split("\n\n")[0]
    with pytest.raises(ValueError, match="complete"):
        context_chunks(code, ".sql", 2, 4, 50)
    with pytest.raises(ValueError, match="statement|block"):
        context_chunks(code, ".sql", 1, 4, 10)


def test_sas_chunks_keep_data_and_macro_blocks_intact() -> None:
    """Verify that sas chunks keep data and macro blocks intact."""
    from dataforge.llm_resources import context_chunks

    first = "data work.x;\nset raw.a;\nkeep id;\nrun;"
    second = "%macro example;\ndata work.y;\nset raw.b;\nrun;\n%mend;"
    chunks = context_chunks(first + "\n" + second, ".sas", 1, 9, 65)
    assert [c["code"] for c in chunks] == [first, second]
    assert chunks[1]["first"] == 5


def test_interactive_sas_procedure_is_not_split_at_run() -> None:
    """Verify that interactive sas procedure is not split at run."""
    from dataforge.llm_resources import context_chunks

    code = "proc datasets library=work;\nmodify first;\nrename x=y;\nrun;\nmodify second;\nrename a=b;\nquit;"
    with pytest.raises(ValueError, match="block"):
        context_chunks(code, ".sas", 1, 7, 90)
    assert context_chunks(code, ".sas", 1, 7, 150)[0]["code"] == code


def test_request_slots_bound_parallelism_release_and_allow_other_workspaces(tmp_path: Path) -> None:
    """Verify that request slots bound parallelism release and allow other workspaces.

    Args:
        tmp_path: Temporary directory supplied by pytest.

    Raises:
        RuntimeError: Raised by the test helper.
    """
    from dataforge.llm_resources import request_slot

    held = threading.Event()
    release = threading.Event()

    def hold() -> None:
        """Handle hold for the test scenario."""
        with request_slot(tmp_path, "a", 1):
            held.set()
            assert release.wait(3)

    thread = threading.Thread(target=hold)
    thread.start()
    assert held.wait(3)
    try:
        with pytest.raises(ValueError, match="busy"):
            with request_slot(tmp_path, "a", 1):
                pytest.fail("over capacity")
        with request_slot(tmp_path, "b", 1):
            pass
    finally:
        release.set()
        thread.join()
    with pytest.raises(RuntimeError):
        with request_slot(tmp_path, "a", 1):
            raise RuntimeError("provider failed")
    with request_slot(tmp_path, "a", 1):
        pass


def test_busy_or_cancelled_assistance_does_not_transmit(tmp_path: Path) -> None:
    """Verify that busy or cancelled assistance does not transmit.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.ingestion import Importer
    from dataforge.llm import assist
    from dataforge.llm_resources import request_slot
    from dataforge.store import Store

    store = Store(tmp_path)
    w = store.create_workspace("Resources")
    Importer(store, w).files([("q.sql", b"select id from raw.a;")], {".sql"})
    fid = store.files(w)[0]["file_id"]
    profile = focused_profile(provider="Ollama", base_url="http://localhost:11434", model="test")
    transport = httpx.MockTransport(lambda req: pytest.fail("request must not be sent"))
    try:
        with request_slot(tmp_path, w, 1):
            assert assist(store, w, profile, fid, 1, 1, transport=transport)["outcome"] == "quarantined"
        with pytest.raises(InterruptedError):
            assist(store, w, profile, fid, 1, 1, transport=transport, cancelled=lambda: True)
    finally:
        store.close()


def test_cancellation_stops_provider_retries() -> None:
    """Verify that cancellation stops provider retries."""
    from dataforge.llm import Adapter, Profile, ProviderError

    cancelled = threading.Event()
    calls = []

    def handler(request: pytest.FixtureRequest) -> Any:
        """Handle handler for the test scenario.

        Args:
            request: Pytest fixture describing the active test request.

        Returns:
            Value produced for the test scenario.
        """
        calls.append(request)
        cancelled.set()
        return httpx.Response(503)

    profile = Profile(provider="Ollama", base_url="http://localhost:11434", model="test", retries=2)
    with Adapter(profile, httpx.MockTransport(handler), cancelled=cancelled.is_set) as adapter:
        with pytest.raises(ProviderError, match="cancelled"):
            adapter.complete("Return JSON", "Synthetic")
    assert len(calls) == 1


def test_chunk_ui_previews_offline_and_sends_only_selected_original_range(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that chunk ui previews offline and sends only selected original range.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    import json
    from functools import partial

    from streamlit.testing.v1 import AppTest

    from dataforge.ingestion import Importer
    from dataforge.llm import assist_task
    from dataforge.services import analyze
    from dataforge.store import Store

    store = Store(tmp_path)
    workspace = store.create_workspace("Chunks")
    lines = ["select id from raw.a /*" + "a" * 300 + "*/;", "select id from raw.b /*" + "b" * 300 + "*/;"]
    Importer(store, workspace).files([("q.sql", "\n".join(lines).encode())], {".sql"})
    analyze(store, workspace)
    profile = focused_profile(provider="Ollama", base_url="http://localhost:11434", model="test")
    store.execute("INSERT INTO llm_profiles VALUES (?,?,?,?)", ["test", workspace, "Test", profile.model_dump_json()])
    store.set_setting(workspace, "default_profile", "test")
    store.set_setting(workspace, "llm_chunk_chars", 500)
    calls = []

    def handler(request: pytest.FixtureRequest) -> Any:
        """Handle handler for the test scenario.

        Args:
            request: Pytest fixture describing the active test request.

        Returns:
            Value produced for the test scenario.
        """
        payload = json.loads(request.content)
        calls.append(json.loads(payload["messages"][1]["content"].split("\n", 1)[1]))
        return httpx.Response(200, json={"message": {"content": '{"claims":[]}'}})

    monkeypatch.setattr("ui.assistance.assist_task", partial(assist_task, transport=httpx.MockTransport(handler)))

    def page(home: "Any", workspace: "Any") -> None:
        """Handle page for the test scenario.

        Args:
            home: Home value used by the test case.
            workspace: Workspace used by the test.
        """
        from dataforge.store import Store
        from ui.assistance import render

        db = Store(home)
        render(db, workspace)
        db.close()

    try:
        app = AppTest.from_function(page, args=(tmp_path, workspace)).run()
        app.checkbox[0].check().run()
        chunk = next(s for s in app.selectbox if s.label == "Context chunk")
        assert len(chunk.options) == 2 and not calls
        chunk.set_value(1).run()
        assert app.code[-1].value == lines[1]
        next(b for b in app.button if b.label == "Analyze selected evidence with AI").click().run()
        assert not app.exception
        assert len(calls) == 1
        assert calls[0]["start_line"] == calls[0]["end_line"] == 2
        assert calls[0]["source"] == lines[1]
        assert len(app.json) >= 1  # Result is rendered on the request's own rerun.
    finally:
        store.close()


def test_provider_connection_checks_share_request_admission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that provider connection checks share request admission.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    from streamlit.testing.v1 import AppTest

    from dataforge.llm_resources import request_slot
    from dataforge.store import Store

    store = Store(tmp_path)
    w = store.create_workspace("Connection admission")
    profile = focused_profile(provider="Ollama", base_url="http://localhost:11434", model="test")
    store.execute("INSERT INTO llm_profiles VALUES (?,?,?,?)", ["profile", w, "Local", profile.model_dump_json()])
    monkeypatch.setattr("ui.provider_settings.Adapter.complete", lambda *args: ('{"status":"connected"}', {}))

    def page(home: "Any", workspace: "Any") -> None:
        """Handle page for the test scenario.

        Args:
            home: Home value used by the test case.
            workspace: Workspace used by the test.
        """
        from dataforge.store import Store
        from ui.provider_settings import render

        db = Store(home)
        render(db, workspace)
        db.close()

    try:
        app = AppTest.from_function(page, args=(tmp_path, w)).run()
        app.selectbox[0].set_value("profile").run()
        with request_slot(tmp_path, w, 1):
            next(b for b in app.button if b.label == "Test model connection").click().run()
        assert not app.exception
        assert any("busy" in error.value for error in app.error)
        assert not app.success
    finally:
        store.close()
