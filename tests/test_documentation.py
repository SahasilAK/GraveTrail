"""Publication boundaries and link checks must fail closed before Pages upload."""
import pytest


def test_publication_filter_excludes_unlisted_files_and_requires_sources(tmp_path):
    from scripts.docs.hooks import public_files

    (tmp_path / "index.md").write_text("# Public", encoding="utf-8")
    (tmp_path / "logo.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "secret.env").write_text("PRIVATE", encoding="utf-8")
    assert public_files(tmp_path, {"index.md", "logo.svg"}) == {"index.md", "logo.svg"}
    with pytest.raises(ValueError, match="missing"):
        public_files(tmp_path, {"missing.md"})
    with pytest.raises(ValueError, match="Unsafe"):
        public_files(tmp_path, {"secret.env"})
    with pytest.raises(ValueError, match="Unsafe"):
        public_files(tmp_path, {"../outside.md"})
    (tmp_path / "KNOWLEDGE.md").write_text("Internal", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsafe"):
        public_files(tmp_path, {"KNOWLEDGE.md"})


def test_document_routes_do_not_collide_on_case_insensitive_hosts():
    from scripts.docs.hooks import page_output

    outputs = {page_output(name) for name in ("ARCHITECTURE.md", "architecture/overview.md", "index.md")}
    assert outputs == {"architecture/index.html", "architecture/overview/index.html", "index.html"}


def test_site_links_validate_project_prefix_fragments_and_missing_targets(tmp_path):
    from scripts.docs.validate import inspect_site

    (tmp_path / "guide").mkdir()
    (tmp_path / "index.html").write_text(
        '<a href="/dataforge-engineering-hub/guide/#install">Install</a>', encoding="utf-8"
    )
    (tmp_path / "guide/index.html").write_text('<h1 id="install">Install</h1>', encoding="utf-8")
    assert inspect_site(tmp_path, "/dataforge-engineering-hub/") == []
    (tmp_path / "index.html").write_text(
        '<a href="guide/#missing">Bad</a><img src="/assets/missing.png">', encoding="utf-8"
    )
    errors = inspect_site(tmp_path, "/dataforge-engineering-hub/")
    assert any("#missing" in error for error in errors)
    assert any("project prefix" in error for error in errors)


def test_output_inventory_rejects_runtime_and_unexpected_files(tmp_path):
    from scripts.docs.validate import inspect_inventory

    (tmp_path / "index.html").write_text("Public", encoding="utf-8")
    assert inspect_inventory(tmp_path, {"index.html"}) == []
    (tmp_path / "workspace.duckdb").write_bytes(b"runtime")
    assert any("workspace.duckdb" in error for error in inspect_inventory(tmp_path, {"index.html"}))
    (tmp_path / "index.html").unlink()
    assert any("Missing" in error for error in inspect_inventory(tmp_path, {"index.html"}))
