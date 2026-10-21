"""Offline immutable project context; no provider calls or parser answer injection."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from dataforge.ai_analysis_models import AnalysisRequest, AnalysisUnit, EvidenceCitation
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


@dataclass(frozen=True)
class PreparedAnalysis:
    workspace: str
    request: AnalysisRequest
    sources: tuple[SourceSnapshot, ...]
    settings_json: str
    prior_revision: str = ''
    manifest_hash: str = ''
    inventory_json: str = '[]'

    @property
    def settings(self):
        return json.loads(self.settings_json)

    @property
    def manifest(self):
        return json.loads(self.inventory_json)


@dataclass(frozen=True)
class AIPlan:
    units: tuple[AnalysisUnit, ...]
    blocked: tuple[dict, ...] = ()
    empty_files: tuple[str, ...] = ()
    catalog: tuple[dict, ...] = ()
    disclosure: tuple[dict, ...] = ()
    context_hash: str = ''
    estimated_characters: int = 0
    max_provider_attempts: int = 0

    @property
    def valid(self):
        return not self.blocked

    def context_for(self, unit):
        if unit.focus:
            f = unit.focus
            visible = unit.code[:f.list_start-unit.start_offset] + unit.code[f.start_offset-unit.start_offset:f.end_offset-unit.start_offset] + unit.code[f.list_end-unit.start_offset:]
        else:
            visible = unit.code
        names = {x.casefold() for x in re.findall(r'[A-Za-z_][\w.]*',visible)}
        return [dict(entry) for entry in self.catalog if entry['unit_id'] not in {unit.unit_id, unit.focus.parent_id if unit.focus else unit.unit_id} and entry['name'].casefold() in names and
                (not entry.get('temporary') or entry['job_id'] == unit.job_id)]


def prepare_analysis(store, workspace, request, *, progress=None):
    """Pin inventory, settings, original bytes and previous publication under one read lock."""
    request = AnalysisRequest.model_validate(request)
    from dataforge.dbt.service import reject_dbt_ai
    reject_dbt_ai(store, workspace, request.file_ids)
    with store.lock:
        inventory = store.files(workspace)
        selected = set(request.file_ids) if request.file_ids is not None else {f['file_id'] for f in inventory}
        if selected - {f['file_id'] for f in inventory}:
            raise ValueError('Selected source does not belong to the workspace')
        settings = ParsingSettings.model_validate({k:store.setting(workspace,k,v)
            for k,v in ParsingSettings().model_dump().items()}).model_dump()
        revisions = store.rows("SELECT run_id FROM analysis_runs WHERE workspace_id=? AND status='completed' ORDER BY created_at DESC LIMIT 1",[workspace])
        sources = []
        if progress:
            progress('Reading selected files', 0, len(selected))
        for f in inventory:
            if f['file_id'] in selected:
                sources.append(SourceSnapshot(f['file_id'],f['content_hash'],f['relative_path'],f['extension'],
                               source_job(f,settings),store.snapshot_content(f)))
                if progress:
                    progress('Reading selected files', len(sources), len(selected))
        sources = tuple(sources)
        manifest = [{'file_id':f['file_id'],'content_hash':f['content_hash'],'path':f['relative_path'],
                     'extension':f['extension'],'job_id':source_job(f,settings)} for f in inventory]
    settings_json = json.dumps(settings,sort_keys=True)
    inventory_json = json.dumps(manifest,sort_keys=True)
    digest = hashlib.sha256((inventory_json+settings_json).encode()).hexdigest()
    return PreparedAnalysis(workspace,request,sources,settings_json,revisions[0]['run_id'] if revisions else '',digest,inventory_json)


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


def plan_ai_units(prepared, *, max_chars=100000, remote=False, allow_full_source=False, progress=None):
    """Page complete units without the manual selector's 50-chunk limit."""
    if type(max_chars) is not int or not 1 <= max_chars <= 200000:
        raise ValueError('Invalid complete-unit budget')
    units,blocked,empty,disclosure,catalog = [],[],[],[],[]
    for index, source in enumerate(prepared.sources):
        if progress:
            progress('Splitting source into tasks', index, len(prepared.sources))
        if source.extension not in {'.sql','.sas'}:
            continue
        spans = list(_unit_spans(source.code,source.extension))
        from dataforge.ai_semantic import proc_sql_spans
        spans = [part for a,b in spans for part in (
            [(a+x,a+y) for x,y in proc_sql_spans(source.code[a:b])]
            if source.extension == '.sas' and b-a > max_chars and proc_sql_spans(source.code[a:b]) else [(a,b)])]
        if not spans:
            empty.append(source.file_id)
        disclosure.append({'file_id':source.file_id,'path':source.path,'content_hash':source.content_hash,
                           'characters':len(source.code),'complete_source':True,'job_id':source.job_id})
        if remote and spans and not allow_full_source:
            blocked.append({'file_id':source.file_id,'reason':'complete_source_permission_required'})
        for start,end in spans:
            code = source.code[start:end]
            if len(code) > max_chars:
                blocked.append({'file_id':source.file_id,'start_offset':start,'reason':'indivisible_unit_exceeds_budget'})
                continue
            unit = AnalysisUnit(unit_id=stable_id(prepared.workspace,source.file_id,source.content_hash,str(start),str(end)),
                file_id=source.file_id,content_hash=source.content_hash,path=source.path,extension=source.extension,
                job_id=source.job_id,first=source.code.count('\n',0,start)+1,last=source.code.count('\n',0,end)+1,
                start_offset=start,end_offset=end,code=code)
            units.append(unit)
            # Only declarations/references and coordinates are shared, never parser relationships.
            clean = re.sub(r"'([^']|'')*'", "''", re.sub(r'--[^\n]*','',strip_comments(code)))
            for match in re.finditer(r'\b(create\s+(?:table|view)|from|join|into|update|using|data|set)\s+([A-Za-z_][\w.]*)',clean,re.I):
                name = match[2]
                catalog.append({'name':name,'role':'declaration' if match[1].lower().startswith('create') else 'observed',
                    'verified_schema':False,'temporary':name.lower().startswith('work.'),'job_id':source.job_id,
                    'file_id':source.file_id,'content_hash':source.content_hash,'unit_id':unit.unit_id})
    if progress:
        progress('Splitting source into tasks', len(prepared.sources), len(prepared.sources))
    # Extract declaration metadata only; never provide parser relationships or transformations.
    from dataforge.parsers.sql import parse_sql
    declaration_groups = {}
    for index, unit in enumerate(units):
        if progress:
            progress('Building shared source context', index, len(units))
        if unit.extension != '.sql':
            continue
        dialect = prepared.settings.get('dialect_by_extension',{}).get(unit.extension,prepared.settings.get('dialect',''))
        for prefix,override in sorted(prepared.settings.get('dialect_by_folder',{}).items(),key=lambda x:len(x[0])):
            if unit.path.startswith(prefix):
                dialect = override
        for record in parse_sql(unit.code,dialect).metadata.get('declared_schemas',[]):
            name = record['table']
            temporary = name.casefold().startswith('work.')
            entry = {'name':name,'role':'declaration','verified_schema':bool(record['columns']),
                'schema_status':'declared' if record['columns'] else 'unresolved','columns':record['columns'] or [],
                'temporary':temporary,'job_id':unit.job_id,'file_id':unit.file_id,'content_hash':unit.content_hash,
                'unit_id':unit.unit_id,'evidence':EvidenceCitation.from_unit(unit).model_dump()}
            declaration_groups.setdefault((name.casefold(),unit.job_id if temporary else ''),[]).append(entry)
    if progress:
        progress('Building shared source context', len(units), len(units))
    for entries in declaration_groups.values():
        signatures = {json.dumps(entry['columns'],sort_keys=True) for entry in entries}
        conflict = len(signatures) != 1 or any(not entry['columns'] for entry in entries)
        for entry in entries:
            if conflict:
                entry.update(columns=[],schema_status='unresolved',verified_schema=False)
            catalog.append(entry)
    catalog = sorted(catalog,key=lambda x:(x['name'].casefold(),x['job_id'],x['unit_id']))
    context_hash = hashlib.sha256(json.dumps({'catalog':catalog,'settings':prepared.settings,'disclosure':disclosure},sort_keys=True).encode()).hexdigest()
    ceiling = len(units) * (2 if prepared.request.additional_ai_review else 1)
    return AIPlan(tuple(units),tuple(blocked),tuple(empty),tuple(catalog),tuple(disclosure),context_hash,
                  sum(len(u.code) for u in units),ceiling)


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
