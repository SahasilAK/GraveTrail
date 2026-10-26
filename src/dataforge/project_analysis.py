"""Permission-gated project build adapters; all engines share analysis_service."""
from dataforge.agent.contracts import AgentError
from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.analysis_service import analysis_report, preview_analysis, run_analysis
from dataforge.connections import RuntimeConnections
from dataforge.credentials import credential_source
from dataforge.provider_service import authorize_provider

READS = {'analysis_preview', 'analysis_report'}
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

    def _job_cancel(self, w, opts, job_id):
        self._workspace(w, write=True)
        record = self.jobs.read(job_id, w)
        if record['operation'] not in {'analyze', 'ai_analysis'}:
            raise AgentError('invalid_argument', 'This job does not support cooperative cancellation')
        return self.jobs.cancel(job_id, w)
