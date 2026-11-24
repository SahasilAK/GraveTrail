"""Permission-gated project build adapters; all engines share analysis_service."""
from dataforge.agent.contracts import AgentError, compact
from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_inspection import inspection_diagnostics, inspection_items, inspection_payload
from dataforge.analysis_service import analysis_report, preview_analysis, run_analysis
from dataforge.connections import RuntimeConnections
from dataforge.credentials import credential_source
from dataforge.provider_service import authorize_provider

READS = {'analysis_preview', 'analysis_report', 'analysis_runs', 'analysis_attempts', 'analysis_attempt_content'}
WRITES = {'job_cancel'}


class _BoundConnections(RuntimeConnections):
    def __init__(self, service, workspace, profile_id=None, profile=None):
        super().__init__()
        self.service, self.workspace = service, workspace
        self.profile_id, self.profile = profile_id, profile
        self._workspace = (service.store.home, workspace)
        self._profile = (profile_id, profile)

    def for_profile(self, profile_id, profile):
        return _BoundConnections(self.service, self.workspace, profile_id, profile)

    def resolve(self, name):
        if self.profile is not None and self.profile.key_env == name:
            if credential_source(name) == 'saved':
                self.service._workspace(self.workspace, source=True)
                authorize_provider(self.service.store, self.service.policy, self.workspace, self.profile)
            manager = self.service._runtime_manager(self.workspace, self.profile_id, self.profile)
            if manager is not None and manager.registered('DATAFORGE_RUNTIME_CREDENTIAL'):
                return manager.resolve('DATAFORGE_RUNTIME_CREDENTIAL')
            if manager is not None:
                secret = manager.for_workspace(self.service.store.home, self.workspace).for_profile(
                    self.profile_id, self.profile).resolve(name)
                if secret:
                    self._request_secrets.add(secret)
                return secret
        return super().resolve(name)

    def redact(self, text, request_secrets=()):
        for manager in self.service.runtime_connections.values():
            text = manager.redact(text, request_secrets)
        return super().redact(text, request_secrets)


class ProjectAnalysisOperations:
    def _analysis_preview(self, w, opts, **arguments):
        self._workspace(w, source=True)
        return preview_analysis(self.store, w, AnalysisRequest.model_validate(arguments),
                                connections=_BoundConnections(self, w))

    def _start_project_analysis(self, w, request):
        self._workspace(w, write=True, source=True)
        self.policy.require('network')
        return self.jobs.start(w, 'ai_analysis', lambda progress, cancelled: self._run_project_analysis(
            w, request, progress=progress, cancelled=cancelled), cancellable=True)

    def _run_project_analysis(self, w, request, *, progress=None, cancelled=None):
        self._workspace(w, write=True, source=True)
        self.policy.require('network')
        manager = _BoundConnections(self, w)

        def authorize(profile):
            self._workspace(w, write=True, source=True)
            self.policy.require('network')
            authorize_provider(self.store, self.policy, w, profile)

        return run_analysis(self.store, w, request, connections=manager, authorize=authorize,
            progress=progress, cancelled=cancelled, transport=self.provider_transport).model_dump()

    def _analysis_report(self, w, opts, run_id=None):
        if opts.detail_level == 'detailed':
            self._workspace(w, source=True)
        report = analysis_report(self.store, w, run_id, include_source=opts.detail_level == 'detailed')
        return self._page(w, opts, ['analysis_report', report['run_id'], opts.detail_level], report['claims'],
            run_id=report['run_id'], mode=report['mode'], status=report['status'], summary=report['summary'],
            unit_count=len(report['units']))

    def _analysis_runs(self, w, opts):
        rows = self.store.rows('''SELECT run_id,mode,status,created_at FROM ai_analysis_runs
            WHERE workspace_id=? ORDER BY created_at DESC,run_id LIMIT ?''', [w, opts.max_items + 1])
        return self._page(w, opts, ['analysis_runs'], rows[:opts.max_items],
                          boundaries=['items'] if len(rows) > opts.max_items else [])

    def _analysis_attempts(self, w, opts, run_id, offset=0):
        if opts.cursor:
            raise AgentError('invalid_argument', 'Use next_offset for project analysis attempts')
        result = inspection_items(self.store, w, run_id, offset=offset, limit=min(opts.limit, 100))
        items = result['items']
        response = {'run_id': run_id, 'offset': offset, 'total': result['total']}
        while True:
            end = offset + len(items)
            response.update(items=items, count=len(items), complete=end >= result['total'],
                            next_offset=end if end < result['total'] else None)
            if len(compact(response)) <= opts.max_chars:
                return response
            if len(items) <= 1:
                raise AgentError('budget_too_small', 'An inspection item exceeds the response budget')
            items = items[:-1]

    def _analysis_attempt_content(self, w, opts, run_id, attempt_id, kind, offset=0, length=16000):
        self._workspace(w, source=True)
        if type(offset) is not int or offset < 0 or type(length) is not int or not 1 <= length <= 16000:
            raise AgentError('invalid_argument', 'Use a nonnegative character offset and length 1–16000')
        if kind == 'diagnostics':
            text = compact(inspection_diagnostics(self.store, w, run_id, attempt_id))
            payload = {'status': 'available', 'redacted': False, 'total_chars': len(text),
                       'content': text[offset:offset + length]}
        else:
            payload = inspection_payload(self.store, w, run_id, attempt_id, kind, offset=offset, limit=length)
        response = {**payload, 'run_id': run_id, 'attempt_id': attempt_id, 'kind': kind, 'offset': offset}
        while True:
            content = response['content']
            end = offset + len(content or '')
            response['has_more'] = content is not None and end < response['total_chars']
            response['next_offset'] = end if response['has_more'] else None
            if len(compact(response)) <= opts.max_chars:
                return response
            if content is None or len(content) <= 1:
                raise AgentError('budget_too_small', 'Inspection metadata exceeds the response budget')
            response['content'] = content[:len(content) // 2]

    def _job_cancel(self, w, opts, job_id):
        self._workspace(w, write=True)
        record = self.jobs.read(job_id, w)
        if record['operation'] not in {'analyze', 'ai_analysis', 'migration', 'migration_convert',
                                       'migration_stage_request', 'workspace_example'}:
            raise AgentError('invalid_argument', 'This job does not support cooperative cancellation')
        return self.jobs.cancel(job_id, w)
