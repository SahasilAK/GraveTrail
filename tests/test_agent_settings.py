from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_agent_settings_permissions_examples_and_connection(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=20).run()
    app.switch_page("ui/pages/settings.py").run()
    app.segmented_control[0].set_value("Agent & Automation Access").run()
    assert not app.exception
    assert any("[mcp_servers.dataforge]" in code.value for code in app.code)
    next(b for b in app.button if b.label == "Test local agent access").click().run()
    assert any("Local agent access works" in s.value for s in app.success)
    next(c for c in app.checkbox if c.label == "Allow source retrieval").uncheck()
    next(b for b in app.button if b.label == "Save agent access settings").click().run()
    assert not app.exception
    assert not next(c for c in app.checkbox if c.label == "Allow source retrieval").value
    next(c for c in app.checkbox if c.label == "Enable agent access for this workspace").uncheck()
    next(b for b in app.button if b.label == "Save agent access settings").click().run()
    next(b for b in app.button if b.label == "Test local agent access").click().run()
    assert any("disabled" in e.value.lower() for e in app.error)
