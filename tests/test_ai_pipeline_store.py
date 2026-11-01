import pytest

from dataforge.ai_analysis_store import save_run
from dataforge.store import Store


def test_parallel_attempts_recover_independently_and_finish_idempotently(tmp_path):
    from dataforge.ai_pipeline_store import begin_attempt, finish_attempt, recover_pipeline, save_request
    store = Store(tmp_path)
    w = store.create_workspace('pipeline')
    save_run(store, w, 'run', mode='ai')
    for batch in ('a', 'b'):
        save_request(store, w, 'run', batch, ['unit-' + batch])
    a = begin_attempt(store, w, 'run', 'a', 100)
    b = begin_attempt(store, w, 'run', 'b', 200)
    finish_attempt(store, w, 'run', a, 'received')
    finish_attempt(store, w, 'run', a, 'received')
    store.execute("UPDATE ai_analysis_requests SET status='completed' WHERE batch_id='a'")
    with pytest.raises(ValueError):
        begin_attempt(store, 'another-workspace', 'run', 'a', 100)
    store.close()
    store = Store(tmp_path)
    recovered = recover_pipeline(store, w, 'run')
    assert [r['attempt_id'] for r in recovered['unknown']] == [b]
    assert len(store.rows('SELECT * FROM ai_analysis_attempts')) == 2
    assert store.rows('SELECT status FROM ai_analysis_attempts WHERE attempt_id=?', [a])[0]['status'] == 'received'
    store.close()
