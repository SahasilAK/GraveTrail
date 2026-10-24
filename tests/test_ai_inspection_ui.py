from streamlit.testing.v1 import AppTest

from dataforge.ai_analysis_store import save_run
from dataforge.ai_pipeline_store import begin_attempt, save_request
from dataforge.store import Store


def test_inspection_is_lazy_and_preserves_selection_without_provider_calls(tmp_path, monkeypatch):
    import ui.analysis_inspection as ui
    from dataforge.ai_inspection import capture_payload
    store = Store(tmp_path)
    workspace = store.create_workspace('small')
    store.set_setting(workspace, 'llm_history', True)
    save_run(store, workspace, 'r', mode='ai', status='cancelled')
    save_request(store, workspace, 'r', 'q', ['p'], details={'work_kind': 'context_completion'})
    ticket = begin_attempt(store, workspace, 'r', 'q', 100)
    capture_payload(store, workspace, 'r', ticket, 'input', b'{"actual":"request"}')
    capture_payload(store, workspace, 'r', ticket, 'output', b'malformed response')
    original, loads = ui.inspection_payload, []
    def read(*args, **kwargs):
        loads.append(args[-1])
        return original(*args, **kwargs)
    monkeypatch.setattr(ui, 'inspection_payload', read)
    monkeypatch.setattr('dataforge.llm.Adapter.complete', lambda *a: (_ for _ in ()).throw(AssertionError('Provider call')))
    def app(store, workspace):
        from ui.analysis_inspection import render_inspection
        render_inspection(store, workspace, 'r')
    view = AppTest.from_function(app, args=(store, workspace)).run()
    assert not view.exception and not loads
    # AppTest does not expose expander interaction; use its public keyed widget state.
    view.session_state[f'ai_inspect_{workspace}_r_input'] = True
    view.run()
    assert not view.exception and not loads, 'An expanded section must still require item expansion'
    view.session_state[f'ai_inspect_{workspace}_r_input_{ticket}'] = True
    view.run()
    assert not view.exception and loads == ['input']
    assert any(c.value == '{"actual":"request"}' for c in view.code)
    selection = view.selectbox[0].value
    view.run()
    assert view.selectbox[0].value == selection
    assert len(loads) == 2 and set(loads) == {'input'}
    store.close()
