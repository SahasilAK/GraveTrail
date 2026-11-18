import threading
from pathlib import Path

import httpx
import pytest
from focused_test_profiles import focused_profile


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
