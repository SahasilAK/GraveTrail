"""Offline immutable project context; no provider calls or parser answer injection."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.asset_identity import source_job
from dataforge.configuration import ParsingSettings
from dataforge.models import stable_id, statements
from dataforge.parsers.sas import strip_comments


@dataclass(frozen=True)
class SourceSnapshot:
    file_id: str
    content_hash: str
    path: str
    extension: str
    job_id: str
    code: str
    source_kind: str = ''
    context_json: str = '{}'
    dialect: str | None = None


def plan_file_parts(source, context, limits):
    """Prefer whole files; split exact contiguous ranges, never semantic products."""
    from dataforge.ai_analysis_models import FilePart
    from dataforge.ai_batching import RECOVERY_FEEDBACK_RESERVE, pack_request
    if source.source_kind not in {'sql', 'sas', 'dbt'}:
        return []
    def part(start, end, index):
        result = FilePart(part_id=stable_id('extraction5', source.file_id, source.content_hash, str(start), str(end)),
            file_id=source.file_id, content_hash=source.content_hash, source_kind=source.source_kind,
            start_offset=start, end_offset=end, part_index=index, scope=source.job_id)
        if context.get('index'):
            from dataforge.ai_context_index import context_for_part
            selected = context_for_part(context['index'], result, context['context_budget'])
            result = result.model_copy(update={'context_ids': [e.entry_id for e in selected.entries],
                'context_hashes': [selected.fingerprint],
                'context_references': [r for e in selected.entries for r in e.evidence],
                'context_omissions': [*selected.omitted, *selected.unresolved]})
        return result
    def fit(candidate):
        definitions = {}
        if context.get('index'):
            from dataforge.ai_context_index import context_for_part
            definitions[candidate.part_id] = context_for_part(context['index'], candidate, context['context_budget']).wire
        return pack_request([candidate], limits, {'sources': {source.file_id: source}, 'definitions': definitions,
                                                  'recovery_feedback': {candidate.part_id: RECOVERY_FEEDBACK_RESERVE},
                                                  'settings': context.get('settings', {})})
    # Fail fixed protocol/configuration errors before trying source subdivisions.
    probe = part(0, 0, 0)
    fit(probe)
    result, start = [], 0
    boundaries = [end for _, end in _unit_spans(source.code, source.extension)]
    while start < len(source.code) or not result:
        end = len(source.code)
        candidate = part(start, end, len(result))
        try:
            fit(candidate)
        except ValueError:
            low, high, fitting = start + 1, end, start
            while low <= high:
                mid = (low + high) // 2
                try:
                    fit(part(start, mid, len(result)))
                    fitting, low = mid, mid + 1
                except ValueError:
                    high = mid - 1
            if fitting == start:
                raise ValueError('minimum_source_part_exceeds_budget') from None
            natural = [b for b in boundaries if start < b <= fitting]
            end = max(natural) if natural else fitting
            candidate = part(start, end, len(result))
        result.append(candidate)
        start = candidate.end_offset
        if start == len(source.code):
            break
    return result


@dataclass(frozen=True)
class PreparedAnalysis:
    workspace: str
    request: AnalysisRequest
    sources: tuple[SourceSnapshot, ...]
    settings_json: str
    prior_revision: str = ''
    manifest_hash: str = ''
    inventory_json: str = '[]'
    inventory_revision: str = ''

    @property
    def settings(self):
        return json.loads(self.settings_json)

    @property
    def manifest(self):
        return json.loads(self.inventory_json)


def prepare_analysis(store, workspace, request, *, progress=None):
    """Pin inventory, settings, original bytes and previous publication under one read lock."""
    request = AnalysisRequest.model_validate(request)
    from dataforge.services import explicit_source_dialect, source_dialect
    with store.lock:
        inventory = store.files(workspace)
        selected = set(request.file_ids) if request.file_ids is not None else {f['file_id'] for f in inventory}
        if selected - {f['file_id'] for f in inventory}:
            raise ValueError('Selected source does not belong to the workspace')
        from dataforge.dbt.ai_context import prepare_dbt_context
        dbt_contexts, closure = prepare_dbt_context(store, workspace, inventory, selected)
        selected |= closure
        settings = ParsingSettings.from_store(store, workspace).model_dump()
        revisions = store.rows("SELECT run_id FROM analysis_runs WHERE workspace_id=? AND status='completed' ORDER BY created_at DESC LIMIT 1",[workspace])
        sources = []
        if progress:
            progress('Reading selected files', 0, len(selected))
        for f in inventory:
            if f['file_id'] in selected:
                sources.append(SourceSnapshot(f['file_id'],f['content_hash'],f['relative_path'],f['extension'],
                               dbt_contexts.get(f['file_id'], {}).get('project_id', source_job(f,settings)),store.snapshot_content(f),
                               'dbt' if f['file_id'] in dbt_contexts else f['extension'].lstrip('.'),
                               json.dumps(dbt_contexts.get(f['file_id'], {}), sort_keys=True),
                               source_dialect(f, settings) if f['extension'] == '.sql' and f['file_id'] not in dbt_contexts else None))
                if progress:
                    progress('Reading selected files', len(sources), len(selected))
        sources = tuple(sources)
        families = {s.source_kind for s in sources if s.source_kind in {'sql', 'sas', 'dbt'}}
        if len(families) > 1:
            raise ValueError('Select one analysis family per build: SQL, SAS, or dbt')
        manifest = [{'file_id':f['file_id'],'content_hash':f['content_hash'],'path':f['relative_path'],
                     'extension':f['extension'],'job_id':source_job(f,settings),
                     'dialect': source_dialect(f, settings),
                     'sql_dialect_override': explicit_source_dialect(f)} for f in inventory]
        if dbt_contexts:
            settings['dbt'] = store.setting(workspace, 'dbt', {})
    settings_json = json.dumps(settings,sort_keys=True)
    inventory_json = json.dumps(manifest,sort_keys=True)
    digest = hashlib.sha256((inventory_json+settings_json).encode()).hexdigest()
    return PreparedAnalysis(workspace,request,sources,settings_json,revisions[0]['run_id'] if revisions else '',digest,inventory_json,
                            inventory_revision(store, workspace))


def inventory_revision(store, workspace):
    return store.rows("""SELECT md5(coalesce(string_agg(file_id || content_hash || relative_path || extension ||
        coalesce(ingestion_id,''), '|' ORDER BY file_id),'')) AS fingerprint
        FROM source_files WHERE workspace_id=?""", [workspace])[0]['fingerprint']


def _unit_spans(code, extension):
    """Reuse lexical statement boundaries, joining complete SAS macro/DATA/PROC blocks."""
    cursor, block_start, block_kind, depth = 0,None,'',0
    for raw, _, _ in statements(code,sas=extension == '.sas'):
        start = code.find(raw,cursor)
        if start < 0:
            raise ValueError('Unable to bind complete original statement')
        end = start + len(raw)
        cursor = end
        clean = re.sub(r'--[^\n]*','',strip_comments(raw)).strip().casefold()
        if not clean:
            continue
        if extension == '.sas':
            if re.match(r'%macro\b',clean):
                depth += 1
                if block_start is None:
                    block_start = start
            if depth:
                if re.match(r'%mend\b',clean):
                    depth -= 1
                    if not depth:
                        yield block_start,end
                        block_start = None
                continue
            header = re.match(r'(data|proc)\b\s*(\w*)',clean)
            if header and block_start is None:
                block_start = start
                run_procs = {'sort','means','summary','transpose','import','export','print','freq','contents'}
                block_kind = 'run' if header[1] == 'data' or header[2] in run_procs else 'quit'
            if block_start is not None:
                if re.match(r'quit\b',clean) or (block_kind == 'run' and re.match(r'run\b',clean)):
                    yield block_start,end
                    block_start = None
                continue
        yield start,end
    if block_start is not None:
        yield block_start,len(code.rstrip())


class AIExecutionContext:
    """Memory-only authorization, conservative attempt ledger and cooperative deadline."""
    def __init__(self, request, *, connections=None, authorize=None, cancelled=None, transport=None,
                 clock=None, catalog=None, settings=None, review_candidates=None, source_hashes=None):
        import time
        validated = AnalysisRequest.model_validate(request)
        self.request = validated.model_copy(update={k: getattr(validated, k) or v for k, v in
            {'max_provider_attempts': 200, 'max_output_tokens_total': 200000, 'max_seconds': 1800}.items()})
        self.connections = connections
        self.authorize = authorize
        self.cancelled = cancelled
        self.transport = transport
        self.clock = clock or time.monotonic
        self.started = self.clock()
        self.attempts = 0
        self.reserved_output_tokens = 0
        self.catalog = catalog or []
        self.settings = settings or {}
        self.review_candidates = review_candidates or []
        self.source_hashes = source_hashes or {}
        self.attempt_log = []

    def check(self):
        if self.cancelled and self.cancelled():
            raise InterruptedError('AI analysis cancelled')
        if self.clock() - self.started >= self.request.max_seconds:
            raise TimeoutError('deadline_exceeded')

    @property
    def remaining_seconds(self):
        self.check()
        return self.request.max_seconds - (self.clock()-self.started)

    def before_attempt(self, profile):
        self.check()
        if self.authorize:
            self.authorize(profile)
        if self.attempts >= self.request.max_provider_attempts:
            raise ValueError('AI provider attempt budget exhausted')
        if self.reserved_output_tokens + profile.max_tokens > self.request.max_output_tokens_total:
            raise ValueError('AI output token reservation budget exhausted')
        self.attempts += 1
        self.reserved_output_tokens += profile.max_tokens
        self.attempt_log.append({'attempt':self.attempts,'model':profile.model,'provider':profile.provider,
                                 'reserved_output_tokens':profile.max_tokens,'outcome':'unknown'})
        if getattr(self, 'journal_attempt', None):
            self.journal_attempt()
        return min(profile.timeout,self.remaining_seconds)
