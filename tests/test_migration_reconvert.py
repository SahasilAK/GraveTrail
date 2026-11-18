from contextlib import closing

import pytest

from dataforge.ingestion import Importer
from dataforge.migration import engine, service
from dataforge.store import Store


def test_reconvert_resumes_from_pinned_sources_and_preserves_revision_history(tmp_path, monkeypatch):
    code = "CREATE VIEW a AS SELECT 1 AS id; CREATE VIEW b AS SELECT id FROM a;"
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace("Migration")
        Importer(store, workspace).files([("input.sql", code.encode())], {".sql"})
        source, = store.files(workspace)
        snapshot = service.freeze(store, workspace, selection=[source["file_id"]],
                                  warehouse="databricks", catalog="main", schema="migration")
        project = service.create_project(store, workspace, "Migration", snapshot)
        pid = project["id"]
        draft = service.convert(store, workspace, pid, project["revision"])
        edit = service.propose(draft, {"a": "SELECT 2 AS id\n"}, "Fix projection")
        edited = service.apply(store, workspace, pid, edit)
        configured = service.revise_schemas(store, workspace, pid, edited["id"], {"types": {"a.id": "BIGINT"}})
        pinned_project, _ = service.load(store, workspace, pid)
        findings = service.report(pinned_project, configured)["findings"]
        obligations = [row["id"] for row in findings if row["model"] == "a" and not row["inherited_from"]]
        reviewed = service.record_review(store, workspace, pid, configured["id"], "a", "Engineer",
                                         "Checked the projection.", obligations)

        Importer(store, workspace).files([("input.sql", b"CREATE VIEW c AS SELECT 3 AS id;")], {".sql"})
        current_source, = store.files(workspace)
        assert current_source["content_hash"] != source["content_hash"]
        monkeypatch.setattr(engine, "VERSION", draft["plan"]["version"] + 1)
        cancel = False

        def cancel_before_publish(fraction, _stage):
            nonlocal cancel
            cancel = fraction >= .85

        with pytest.raises(InterruptedError):
            service.convert(store, workspace, pid, reviewed["id"], cancelled=lambda: cancel,
                            progress=cancel_before_publish, reconvert=True)
        assert service.load(store, workspace, pid)[1] == reviewed

    with closing(Store(tmp_path)) as store:
        stages = []
        fresh = service.convert(store, workspace, pid, reviewed["id"], reconvert=True,
                                progress=lambda _, stage: stages.append(stage))
        assert any(stage.startswith("Resuming 2 saved model conversions") for stage in stages)
        assert fresh["parent"] == reviewed["id"] and fresh["id"] != reviewed["id"]
        assert fresh["plan"]["version"] == draft["plan"]["version"] + 1
        assert set(fresh["files"]) == {"a", "b"}
        assert fresh["files"]["a"]["sql"].split() == ["SELECT", "1", "AS", "id"]
        assert fresh["reviews"] == fresh["settings"] == {}
        assert service.load(store, workspace, pid)[0]["snapshot"] == pinned_project["snapshot"]
        assert service.evidence(store, workspace, pid, fresh["plan"]["regions"][0]) in code
        assert service.load(store, workspace, pid, reviewed["id"])[1] == reviewed
        with pytest.raises(ValueError, match="Migration changed"):
            service.convert(store, workspace, pid, reviewed["id"], reconvert=True)

        restored = service.restore_revision(store, workspace, pid, fresh["id"], reviewed["id"])
        assert restored["files"] == reviewed["files"]
        assert restored["reviews"] == reviewed["reviews"]
        assert restored["settings"] == reviewed["settings"]
