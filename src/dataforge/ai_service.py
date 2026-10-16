"""Offline evidence previews and explicit grounded AI requests over existing contracts."""
import json

from dataforge.agent.contracts import AgentError
from dataforge.asset_identity import source_job
from dataforge.assistance_queue import diagnostic_context, diagnostic_queue
from dataforge.configuration import ParsingSettings
from dataforge.connections import RuntimeConnections, connection_scope
from dataforge.llm import TASKS, assist_task, merge_claims
from dataforge.llm_resources import context_chunks
from dataforge.provider_service import authorize_provider
from dataforge.services import analyze

READS = {'ai_chunks', 'review_list', 'review_preview', 'ai_results', 'ai_result', 'ai_activity'}
WRITES = {'ai_request', 'review_request', 'ai_merge'}
SOURCE = {'ai_chunks', 'review_preview', 'ai_request', 'review_request', 'ai_merge'}


def preview_ai_evidence(store, workspace, file_id, first, last, task):
    if task not in TASKS or type(first) is not int or type(last) is not int:
        raise AgentError('validation_failed', 'Select a supported task and integer source bounds')
    source = store.file(file_id)
    if source['workspace_id'] != workspace or source['extension'] not in {'.sql', '.sas'}:
        raise AgentError('not_found', 'Select an SQL/SAS source in this workspace')
    chunks = context_chunks(source['raw_content'], source['extension'], first, last,
        min(store.setting(workspace, 'llm_chunk_chars', 4000), store.setting(workspace, 'max_context_chars', 8000)))
    config = {k: store.setting(workspace, k, v) for k, v in ParsingSettings().model_dump().items()}
    return {'file_id': file_id, 'content_hash': source['content_hash'], 'job_id': source_job(source, config),
            'task': task, 'chunks': chunks, 'first': first, 'last': last,
            'max_context_chars': store.setting(workspace, 'max_context_chars', 8000)}


def merge_ai_result(store, workspace, record_id, refresh=True):
    records = store.rows('SELECT outcome,details,task FROM llm_records WHERE workspace_id=? AND record_id=?', [workspace, record_id])
    if not records:
        raise AgentError('not_found', 'AI result no longer retained in this workspace')
    row = records[0]
    if row['task'] not in {'sql_lineage', 'sas_lineage', 'lineage_validation'}:
        raise AgentError('validation_failed', 'Advisory results cannot be merged')
    already = row['outcome'] == 'merged'
    try:
        count = len(json.loads(row['details'])['result']['claims']) if already else merge_claims(store, workspace, record_id)
    except ValueError:
        raise AgentError('source_changed', 'Result is unvalidated, source/job changed or evidence no longer resolves; request a new review') from None
    result = {'record_id': record_id, 'merged': count, 'already_merged': already, 'refresh_required': not refresh}
    if refresh:
        try:
            analyze(store, workspace)
        except Exception:
            result['refresh_required'] = True
            result['warning'] = 'Merge committed; graph refresh failed. Retry analysis separately.'
    return result


class AIOperations:
    def _ai_chunks(self, w, opts, file_id, first, last, task):
        self._workspace(w, source=True)
        preview = preview_ai_evidence(self.store, w, file_id, first, last, task)
        chunks = preview.pop('chunks')
        return self._page(w, opts, ['chunks', file_id, first, last, task], chunks, **preview)

    def _review_list(self, w, opts):
        queue = diagnostic_queue(self.store, w)
        return self._page(w, opts, 'review', queue['items'], boundaries=['queue_limit'] if queue['truncated'] else [])

    def _review_preview(self, w, opts, diagnostic_id, first=None, last=None):
        self._workspace(w, source=True)
        item = diagnostic_context(self.store, w, diagnostic_id)
        return self._ai_chunks(w, opts, item['file_id'], item['first'] if first is None else first,
                               item['last'] if last is None else last, item['task'])

    def _review_request(self, w, opts, diagnostic_id, expected_hash, first, last, expected_job='workspace'):
        item = diagnostic_context(self.store, w, diagnostic_id)
        if item['content_hash'] != expected_hash:
            raise AgentError('source_changed', 'Diagnostic source changed; refresh its preview')
        return self._ai_request(w, opts, item['file_id'], first, last, item['task'], expected_hash, expected_job)

    def _ai_request(self, w, opts, file_id, first, last, task, expected_hash, expected_job='workspace'):
        self._workspace(w, write=True, source=True)
        self.policy.require('network')
        preview = preview_ai_evidence(self.store, w, file_id, first, last, task)
        if preview['content_hash'] != expected_hash or preview['job_id'] != expected_job:
            raise AgentError('source_changed', 'Source hash/job changed; refresh the evidence preview')
        manager = RuntimeConnections()

        def authorize(pid, profile):
            self._workspace(w, write=True, source=True)
            authorize_provider(self.store, self.policy, w, profile)
            credentials = self.runtime_connections.get((w, pid), manager)
            if profile.key_env:
                reference = 'DATAFORGE_RUNTIME_CREDENTIAL' if credentials.registered('DATAFORGE_RUNTIME_CREDENTIAL') else profile.key_env
                secret = credentials.resolve(reference)
                if not secret:
                    raise AgentError('credential_unavailable', 'Approved provider credential unavailable')
                manager.register('DATAFORGE_RUNTIME_CREDENTIAL', secret)
                return profile.model_copy(update={'key_env': 'DATAFORGE_RUNTIME_CREDENTIAL'})
            return profile

        try:
            with connection_scope(manager):
                result = assist_task(self.store, w, file_id, first, last, task,
                    transport=self.provider_transport, expected_hash=expected_hash, authorize=authorize)
            # Detailed result retrieval is a separate explicit, source-gated read.
            return {k: v for k, v in result.items() if k != 'result'}
        finally:
            manager.clear()

    def _ai_results(self, w, opts):
        rows = self.store.rows('SELECT record_id,task,file_id,start_line,provider,model,outcome,duration,usage,created_at FROM llm_records WHERE workspace_id=? ORDER BY created_at DESC,record_id', [w])
        return self._page(w, opts, 'ai_results', rows, analysis_current=self._current(w))

    def _ai_activity(self, w, opts):
        return self._ai_results(w, opts)

    def _ai_result(self, w, opts, record_id):
        rows = self.store.rows('SELECT * FROM llm_records WHERE workspace_id=? AND record_id=?', [w, record_id])
        if not rows:
            raise AgentError('not_found', 'AI result no longer retained in this workspace')
        record = rows[0]
        details = json.loads(record.pop('details'))
        warnings = []
        files = [f for f in self.store.files(w) if f['file_id'] == record['file_id']]
        if not files or files[0]['content_hash'] != details.get('content_hash'):
            warnings.append('source_changed_or_removed')
        if files:
            config = {k: self.store.setting(w, k, v) for k, v in ParsingSettings().model_dump().items()}
            if source_job(files[0], config) != details.get('job_id', 'workspace'):
                warnings.append('source_job_changed')
        record.update(schema_version=details.get('schema_version', '1'), content_hash=details.get('content_hash'),
                      job_id=details.get('job_id', 'workspace'), warnings=warnings)
        if opts.detail_level == 'detailed':
            self._workspace(w, source=True)
            record['details'] = details
        return record

    def _ai_merge(self, w, opts, record_id, refresh=True):
        self._workspace(w, write=True, source=True)
        return merge_ai_result(self.store, w, record_id, refresh)
