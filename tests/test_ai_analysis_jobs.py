from dataforge.agent.jobs import Jobs
from dataforge.connections import RuntimeConnections, current_connections


def test_worker_binds_only_initiating_session_and_journal_has_no_secret(tmp_path):
    manager = RuntimeConnections()
    manager.register('DATAFORGE_TEST_KEY', 'synthetic-session-secret')
    jobs = Jobs(tmp_path)
    try:
        def work(progress, cancelled):
            assert not cancelled()
            assert current_connections().resolve('DATAFORGE_TEST_KEY') == 'synthetic-session-secret'
            progress(.5, 'AI extraction')
            return {'status': 'committed', 'requests': 1}

        run = jobs.start('workspace', 'ai_analysis', work, connections=manager, cancellable=True)
        result = jobs.wait(run['job_id'], 'workspace', timeout=5)
        assert result['status'] == 'completed'
        assert result['stage'] == 'AI extraction'
        assert result['created_at'] <= result['started_at'] <= result['stage_started_at'] <= result['finished_at']
        assert 'synthetic-session-secret' not in jobs.path(run['job_id']).read_text()
    finally:
        jobs.close()
