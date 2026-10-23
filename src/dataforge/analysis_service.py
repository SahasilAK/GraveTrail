"""Explicit, staged AI project builds shared by the UI, CLI and MCP.

Provider work never owns a database transaction. Publication rechecks the original
inventory/configuration/revision and commits accepted table/column facts together.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from dataclasses import replace

from dataforge.ai_analysis_models import (
    AnalysisReport,
    AnalysisRequest,
    AnalysisUnit,
    ClaimDecision,
    ProjectLineageResponse,
    ValidationContext,
)
from dataforge.ai_analysis_store import (
    active_project_runs,
    attach_published_support,
    inherited_context_sources,
    load_analysis_report,
    load_validation_checkpoint,
    save_claim_decisions,
    save_run,
    save_unit_result,
    save_validation_checkpoint,
)
from dataforge.ai_budget import execution_budget, resolve_project_allowance
from dataforge.ai_context import AIExecutionContext, plan_ai_units, prepare_analysis
from dataforge.ai_validation import VALIDATOR_VERSION
from dataforge.ai_wire import decode_project_result, encode_project_result
from dataforge.connections import current_connections
from dataforge.llm import (
    analysis_prompt_hash,
    invoke_analysis_unit,
    preview_analysis_routes,
    review_batches,
)
from dataforge.models import ParseResult, stable_id
from dataforge.services import (
    PARSER_VERSION,
    analyze,
    prepare_analysis_results,
    publish_analysis_results,
    restore_manual_ai_results,
)
from dataforge.settings_service import revision


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _state_revision(store, workspace):
    # Explicit manual merges mutate facts without creating an analysis_runs row.
    merged = store.rows("SELECT record_id FROM llm_records WHERE workspace_id=? AND outcome='merged' ORDER BY record_id", [workspace])
    return _hash({'settings': revision(store, workspace), 'merged': merged})


def _usage(counts, result):
    for key, aliases in {'input_tokens': ('input_tokens', 'prompt_tokens', 'promptTokenCount'),
                         'output_tokens': ('output_tokens', 'completion_tokens', 'candidatesTokenCount')}.items():
        value = next((result.usage[k] for k in aliases if isinstance(result.usage.get(k), int)), None)
        if value is not None:
            counts[key] += value


def _prepare(store, workspace, request, connections=None, cancelled=None, transport=None, authorize=None,
             preparation_progress=None):
    try:
        prepared = prepare_analysis(store, workspace, request, progress=preparation_progress)
    except ValueError:
        if request.resume_run_id:
            raise ValueError('source_or_configuration_changed') from None
        raise
    if request.resume_run_id:
        prior=store.rows('SELECT summary FROM ai_analysis_runs WHERE workspace_id=? AND run_id=?',
            [workspace,request.resume_run_id])
        pin=json.loads(prior[0]['summary']).get('pin',{}) if prior else {}
        if pin != {'manifest':prepared.manifest_hash,'revision':_state_revision(store,workspace),
                   'prior':prepared.prior_revision,'protocol':_protocol_hash()}:
            raise ValueError('source_or_configuration_changed')
    plan = plan_ai_units(prepared, max_chars=200000, progress=preparation_progress, adaptive=True)
    execution = AIExecutionContext(request, connections=connections or current_connections(),
        cancelled=cancelled, transport=transport, settings=prepared.settings, authorize=authorize,
        source_hashes={s.file_id: s.content_hash for s in prepared.sources})
    from dataforge.llm import analysis_routes
    try:
        execution.cache_identity = [{k: getattr(profile, k) for k in
            ('provider', 'base_url', 'model', 'max_tokens', 'output_mode', 'temperature', 'structured')}
            for _, profile in analysis_routes(store, workspace, 'project_lineage')]
    except ValueError:
        execution.cache_identity = []
    from dataforge.ai_semantic import (
        projection_count,
        split_proc_sql_unit,
        split_projection_unit,
        unit_dialect,
    )
    if request.resume_run_id:
        rows=store.rows('SELECT result FROM ai_analysis_units WHERE workspace_id=? AND run_id=? ORDER BY file_id,start_char,unit_id',
            [workspace,request.resume_run_id])
        specs=[json.loads(row['result']).get('unit_spec') for row in rows]
        if specs and all(specs):
            sources={source.file_id:source for source in prepared.sources}
            restored=[AnalysisUnit.model_validate({**spec,'code':sources[spec['file_id']].code[spec['start_offset']:spec['end_offset']]}) for spec in specs]
            restored.sort(key=lambda u:(next(i for i,s in enumerate(prepared.sources) if s.file_id==u.file_id),u.start_offset,
                u.focus.ordinal_start if u.focus else 0))
            plan=replace(plan,units=tuple(restored),blocked=())
    else:
        def fit(unit):
            execution.catalog=plan.context_for(unit)
            trial=preview_analysis_routes(store,workspace,[unit],execution)
            from dataforge.ai_citations import source_references
            from dataforge.ai_semantic import source_view
            from dataforge.ai_source_views import visible_identifier_count
            output_pressure = ((visible_identifier_count(unit, source_view(unit, unit_dialect(unit, prepared.settings))) > 64
                or len(source_references(unit, prepared.settings, partial=True)) > 64)
                and (not unit.source_focus or unit.source_focus.end_offset - unit.source_focus.start_offset > 64))
            capacity={'complete_prompt_exceeds_context_budget','complete_prompt_exceeds_model_capacity',
                      'source_context_exceeds_character_allowance'}
            if (not unit.source_focus or unit.source_focus.context_end - unit.source_focus.context_start <= 1) and any(
                    b['reason'] in capacity for b in trial['blocked']):
                from dataforge.ai_source_views import minimum_source_view
                span = None
                if not unit.source_focus:
                    from dataforge.ai_source_views import context_records
                    records = context_records(execution.catalog, prepared.settings)
                    if records:
                        index = max(range(len(records)), key=lambda i: len(json.dumps(records[i], ensure_ascii=False).encode()))
                        span = (index, index + 1)
                probe = preview_analysis_routes(store, workspace, [minimum_source_view(unit,
                    preserve_context=bool(unit.source_focus), context_span=span)], execution)
                if any(b['reason'] in capacity for b in probe['blocked']):
                    return [unit]
            if (projection_count(unit,unit_dialect(unit,prepared.settings))>100 or output_pressure
                    or any(b['reason'] in capacity for b in trial['blocked'])):
                parts = (() if unit.source_focus else
                    split_projection_unit(unit,unit_dialect(unit,prepared.settings)) or split_proc_sql_unit(unit))
                if not parts:
                    from dataforge.ai_source_views import split_source_context
                    parts = split_source_context(unit, execution.catalog, prepared.settings,
                        source_only=output_pressure and not any(b['reason'] in capacity for b in trial['blocked']))
                if parts:
                    return [page for part in parts for page in fit(part)]
            return [unit]
        pages = []
        for index, unit in enumerate(plan.units):
            if preparation_progress:
                preparation_progress('Sizing source tasks', index, len(plan.units))
            pages.extend(fit(unit))
        if preparation_progress:
            preparation_progress('Sizing source tasks', len(plan.units), len(plan.units))
        plan=replace(plan,units=tuple(pages))
    plan=replace(plan,context_hash=_hash({'context':plan.context_hash,
        'partitions':[(u.unit_id,u.focus.model_dump() if u.focus else None) for u in plan.units]}))
    blocked, routes, bundles, allowances, excluded = list(plan.blocked), {}, [], [], []
    reusable, ends, review_provisional = 0, [], False
    expected = _state_revision(store, workspace)
    for index, unit in enumerate(plan.units):
        if preparation_progress:
            preparation_progress('Checking prompt budgets and provider credentials', index, len(plan.units))
        execution.catalog = plan.context_for(unit)
        execution.review_candidates = []
        context_hash = _unit_context_hash(prepared, plan, execution, unit, expected)
        checkpoint = load_validation_checkpoint(store, workspace, request.resume_run_id, unit, context_hash) if request.resume_run_id else None
        if not checkpoint and not request.refresh_ai:
            checkpoint = _prior_checkpoint(store, workspace, unit, context_hash, request)
        cached = None if request.refresh_ai else _cached(store, workspace, unit, context_hash)
        tasks=[]
        if not checkpoint and cached is None:
            tasks.append(('project_lineage',[]))
        else:
            reusable += 1
        if request.additional_ai_review and not (checkpoint and checkpoint[1]):
            if checkpoint:
                if unit.source_focus:
                    from dataforge.ai_composition import review_facts
                    facts = review_facts(checkpoint[0], unit)
                else:
                    from dataforge.ai_reconciliation import reconcile_candidates
                    from dataforge.parsers.sas import parse_sas
                    from dataforge.parsers.sql import parse_sql
                    source=next(source for source in prepared.sources if source.file_id==unit.file_id)
                    settings={**prepared.settings,'dialect':unit_dialect(unit,prepared.settings)}
                    parsed=(parse_sql(source.code,settings['dialect']) if unit.extension=='.sql' else
                        parse_sas(source.code,settings.get('library_mappings'),settings.get('macros'),settings['dialect']))
                    context=ValidationContext(unit=unit,workspace_id=workspace,source_text=source.code,
                        settings=settings,catalog=execution.catalog,parser_result=parsed)
                    facts=[f for f in reconcile_candidates(parsed,checkpoint[0],request.mode,context=context).facts if f.origin=='ai']
                facts = [f for f in facts if f.candidate_id not in checkpoint[0].reviewed_candidates]
                tasks.extend(('lineage_review',batch) for batch in review_batches(facts, unit=unit, settings=prepared.settings))
            else:
                tasks.append(('lineage_review',[]))
                review_provisional = True
        if not tasks:
            bundles.append((0,0,0))
        for task,candidates in tasks:
            execution.review_candidates=candidates
            preview=preview_analysis_routes(store,workspace,[unit],execution,tasks=[task])
            blocked.extend(b for b in preview['blocked'] if not b['reason'].startswith('worst_case_'))
            routes.update(preview['routes'])
            allowances.extend(preview['allowances'])
            excluded.extend(preview['excluded_routes'])
            seconds=sum(p['timeout']*p['attempts_per_unit'] for rr in preview['routes'].values() for p in rr)
            bundles.append((preview['max_provider_attempts'],preview['max_output_tokens_reserved'],seconds))
        ends.append(len(bundles))
    if preparation_progress:
        preparation_progress('Checking prompt budgets and provider credentials', len(plan.units), len(plan.units))
        preparation_progress('Calculating execution budgets', 0, 1)
    execution.review_candidates=[]
    budget=execution_budget(bundles,**{k:getattr(request,k) for k in
        ('max_provider_attempts','max_output_tokens_total','max_seconds')})
    budget['project_allowance'] = resolve_project_allowance(bundles, request)
    execution.request=request.model_copy(update=budget['effective'])
    selected_stages=budget['selected_units']
    if bundles and (not selected_stages or (selected_stages<len(bundles)
            and not any(any(bundle) for bundle in bundles[:selected_stages]))):
        blocked.append({'reason':'single_unit_exceeds_execution_budget'})
    starts=[0,*ends[:-1]]
    budget.update(selected_stages=selected_stages,
        selected_new_units=sum(start<selected_stages and any(any(bundle) for bundle in bundles[start:min(end,selected_stages)])
            for start,end in zip(starts,ends)),
        selected_units=sum(end<=selected_stages for end in ends),
        remaining_units=sum(end>selected_stages for end in ends))
    if preparation_progress:
        preparation_progress('Calculating execution budgets', 1, 1)
    return prepared,plan,execution,{'valid':not blocked,'mode':request.mode,
        'files':len(prepared.sources),'units':len(plan.units),'empty_files':len(plan.empty_files),
        'blocked':blocked,'routes':routes,'disclosure':list(plan.disclosure),
        'allowances':allowances,'excluded_routes':excluded,'reusable_units':reusable,**budget,
        'review_sizing_provisional':review_provisional,
        'semantic_pages':sum(u.focus is not None for u in plan.units),
        'source_context_pages':sum(u.source_focus is not None for u in plan.units),
        'estimated_characters':plan.estimated_characters,'max_provider_attempts':budget['total_attempts'],
        'max_output_tokens_reserved':budget['total_output_tokens'],'manifest_hash':prepared.manifest_hash}


def preview_analysis(store, workspace, request, *, connections=None, progress=None):
    """Offline disclosure/context/budget preview; no connection tests or requests."""
    request = _resume_request(store, workspace, AnalysisRequest.model_validate(request))
    if request.mode == 'parser':
        return {'valid': True, 'mode': 'parser', 'files': len(store.files(workspace)),
                'units': 0, 'blocked': [], 'routes': {}, 'max_provider_attempts': 0}
    return _prepare(store, workspace, request, connections, preparation_progress=progress)[3]


def _current(store, workspace, prepared, expected_revision, *, full=False):
    from dataforge.ai_context import inventory_revision
    prior = store.rows("SELECT run_id FROM analysis_runs WHERE workspace_id=? AND status='completed' ORDER BY created_at DESC LIMIT 1", [workspace])
    if (inventory_revision(store, workspace) != prepared.inventory_revision
            or (prior[0]['run_id'] if prior else '') != prepared.prior_revision
            or _state_revision(store, workspace) != expected_revision):
        raise ValueError('source_or_configuration_changed')
    if full and prepare_analysis(store, workspace, prepared.request).manifest_hash != prepared.manifest_hash:
        raise ValueError('source_or_configuration_changed')


def _unit_context_hash(prepared, plan, execution, unit, expected_revision):
    prompt_hash = analysis_prompt_hash('project_lineage',focused=bool(unit.focus), source_kind=unit.source_kind)
    return _hash({'source': unit.model_dump(exclude={'code'}), 'context': plan.context_for(unit),
        'model_routes': getattr(execution, 'cache_identity', []),
        'settings': prepared.settings, 'prompt': prompt_hash,
        'validator': VALIDATOR_VERSION, 'parser': PARSER_VERSION, 'mode': prepared.request.mode})


def _resume_request(store, workspace, request):
    if not request.resume_run_id:
        return request
    rows = store.rows('SELECT mode,status,summary FROM ai_analysis_runs WHERE workspace_id=? AND run_id=?',
        [workspace, request.resume_run_id])
    if not rows or rows[0]['status'] not in {'awaiting_continuation', 'interrupted', 'cancelled', 'failed'}:
        raise ValueError('Run is not available for continuation')
    summary = json.loads(rows[0]['summary'])
    if 'request' not in summary:
        raise ValueError('This legacy run has no resumable checkpoint')
    saved = summary['request']
    if request.file_ids is not None and request.file_ids != saved['file_ids']:
        raise ValueError('Continuation source selection is pinned')
    if request.mode not in {'parser', saved['mode']}:
        raise ValueError('Continuation analysis mode is pinned')
    return AnalysisRequest.model_validate({**{'auto_continue': False}, **saved, **{k: getattr(request, k) for k in
        ('max_provider_attempts', 'max_output_tokens_total', 'max_seconds', 'resume_run_id', 'retry_unknown')}})


def _cached(store, workspace, unit, context_hash):
    rows = store.rows('''SELECT u.result FROM ai_analysis_units u
        JOIN ai_analysis_runs r ON u.run_id=r.run_id AND u.workspace_id=r.workspace_id
        WHERE u.workspace_id=? AND u.unit_id=? AND u.context_hash=? AND u.status IN ('validated','staged')
        ORDER BY r.created_at DESC LIMIT 1''', [workspace, unit.unit_id, context_hash])
    if not rows:
        return None
    try:
        saved = json.loads(rows[0]['result'])
        if saved.get('checkpoint_version') == 2:
            saved = saved.get('cache')
            if not saved:
                return None
        result = decode_project_result('project_lineage', saved['payload'], unit) if saved.get('wire_version') == 2 else ProjectLineageResponse.model_validate(saved)
        result.assert_unit(unit)
        return result
    except ValueError:
        return None


def _prior_checkpoint(store, workspace, unit, context_hash, request):
    rows = store.rows('''SELECT u.run_id FROM ai_analysis_units u JOIN ai_analysis_runs r
        ON u.run_id=r.run_id AND u.workspace_id=r.workspace_id WHERE u.workspace_id=?
        AND u.unit_id=? AND u.context_hash=? AND u.status IN ('validated','staged')
        ORDER BY r.created_at DESC LIMIT 1''', [workspace, unit.unit_id, context_hash])
    if not rows:
        return None
    checkpoint = load_validation_checkpoint(store, workspace, rows[0]['run_id'], unit, context_hash)
    if checkpoint:
        report, _, record, cache = checkpoint
        from dataforge.ai_composition import review_facts
        candidates = review_facts(report, unit) if unit.source_focus else report.accepted
        reviewed = not request.additional_ai_review or all(f.candidate_id in report.reviewed_candidates for f in candidates)
        return report, reviewed, record, cache


def run_analysis(store, workspace, request, *, connections=None, authorize=None,
                 progress=None, cancelled=None, transport=None):
    """Run only under an explicit user action; failures retain the prior graph."""
    request = AnalysisRequest.model_validate(request)
    manager = connections or current_connections()
    if request.mode == 'hybrid' or request.additional_ai_review:
        return AnalysisReport(mode=request.mode, status='blocked',
            reasons=['Hybrid comparison and additional review are no longer supported; choose parser or ai'])
    try:
        request = _resume_request(store, workspace, request)
    except ValueError as exc:
        return AnalysisReport(mode=request.mode, status='blocked', reasons=[str(exc)])
    if request.mode == 'parser':
        result = analyze(store, workspace, request.file_ids, request.force_parser,
                         progress=progress, cancelled=cancelled)
        return AnalysisReport(run_id=result['run_id'], mode='parser', status='committed', complete=True,
            counts={k: result[k] for k in ('analyzed', 'cached', 'assets', 'edges')})
    run_id = request.resume_run_id or uuid.uuid4().hex
    counts = Counter(units=0, processed=0, cache_hits=0, requests=0, accepted=0, rejected=0,
                     unresolved=0, conflicts=0, input_tokens=0, output_tokens=0)
    usage_known, execution, registered = True, None, False
    stage = 'planning'

    def update(fraction, name):
        if progress:
            progress(fraction, name)

    try:
        if cancelled and cancelled():
            raise InterruptedError('cancelled')
        with store.analysis_lock:
            if active_project_runs(store, workspace):
                raise ValueError('analysis_already_active')
            prepared, plan, execution, preview = _prepare(store, workspace, request, manager,
                cancelled=cancelled, transport=transport)
            expected_revision = _state_revision(store, workspace)
            prior_summary = {}
            if request.resume_run_id:
                prior = store.rows('SELECT * FROM ai_analysis_runs WHERE workspace_id=? AND run_id=?', [workspace, run_id])[0]
                prior_summary = json.loads(prior['summary'])
                pin = prior_summary.get('pin', {})
                if pin != {'manifest': prepared.manifest_hash, 'revision': expected_revision,
                           'prior': prepared.prior_revision, 'protocol': _protocol_hash()}:
                    raise ValueError('source_or_configuration_changed')
                from dataforge.ai_pipeline_store import recover_pipeline
                unknown = recover_pipeline(store, workspace, run_id)['unknown']
                from dataforge.ai_rate_limits import QUOTAS
                for attempt in store.rows('SELECT details FROM ai_analysis_attempts WHERE workspace_id=? AND run_id=?', [workspace, run_id]):
                    details = json.loads(attempt['details'])
                    if details.get('limits') and details.get('quota_scope'):
                        QUOTAS.observe(details['quota_scope'], details['limits'])
                if (prior_summary.get('inflight') or unknown) and not request.retry_unknown:
                    return AnalysisReport(run_id=run_id, mode=request.mode, status='awaiting_continuation',
                        reasons=['unknown_inflight_request_requires_explicit_retry'])
                if request.retry_unknown:
                    for attempt in unknown:
                        store.execute("UPDATE ai_analysis_attempts SET status='retry_authorized' WHERE attempt_id=?", [attempt['attempt_id']])
            execution.prior_requests = prior_summary.get('counts', {}).get('requests', 0)
            execution.prior_reserved = prior_summary.get('counts', {}).get('reserved_output_tokens', 0)
            if request.resume_run_id:
                from dataforge.ai_pipeline_store import attempt_totals
                journal_requests, journal_reserved = attempt_totals(store, workspace, run_id)
                execution.prior_requests = max(execution.prior_requests, journal_requests)
                execution.prior_reserved = max(execution.prior_reserved, journal_reserved)
            execution.project_allowance = prior_summary.get('project_allowance', preview['project_allowance'])
            execution.prior_seconds = prior_summary.get('active_seconds', 0)
            counts['input_tokens'] = prior_summary.get('counts', {}).get('input_tokens', 0)
            counts['output_tokens'] = prior_summary.get('counts', {}).get('output_tokens', 0)
            counts['review_batches'] = prior_summary.get('counts', {}).get('review_batches', 0)
            usage_known = not prior_summary.get('inflight') and prior_summary.get('usage_known', True)


            def authorize_attempt(profile):
                _current(store, workspace, prepared, expected_revision)
                if authorize:
                    authorize(profile)

            execution.authorize = authorize_attempt
            if not preview['valid']:
                raise ValueError('preflight_blocked: ' + ', '.join(sorted({x['reason'] for x in preview['blocked']})))
            context_ids = {c['file_id'] for c in plan.catalog if c.get('role') == 'declaration'}
            context_ids.update(s.file_id for s in prepared.sources if s.source_kind == 'dbt')
            preserved_ids = {m['file_id'] for m in prepared.manifest} - {s.file_id for s in prepared.sources}
            context_sources = {(m['file_id'], m['content_hash']): m
                for m in inherited_context_sources(store, workspace, preserved_ids)}
            context_sources.update({(m['file_id'], m['content_hash']): m
                for m in prepared.manifest if m['file_id'] in context_ids})
            manifest = {'inventory': prepared.manifest,
                        'sources': list(context_sources.values())}
            save_run(store, workspace, run_id, mode=request.mode, manifest=manifest,
                     configuration=prepared.settings, summary={'preview': {k: v for k, v in preview.items()
                         if k not in {'allowances', 'disclosure', 'routes', 'excluded_routes'}}, 'request': request.model_dump(),
                         'pin': {'manifest': prepared.manifest_hash, 'revision': expected_revision,
                                 'prior': prepared.prior_revision, 'protocol': _protocol_hash()},
                         'counts': {**dict(counts), 'requests': execution.prior_requests,
                                    'reserved_output_tokens': execution.prior_reserved}, 'inflight': False,
                         'project_allowance': execution.project_allowance})
            registered = True
            if not request.resume_run_id:
                with store.transaction():
                    for unit in plan.units:
                        from dataforge.ai_pipeline_store import save_context_dependencies
                        dependencies = [{'file_id': unit.file_id, 'content_hash': unit.content_hash,
                                         'kind': 'original', 'source_kind': unit.source_kind}]
                        for entry in plan.context_for(unit):
                            if entry.get('file_id'):
                                dependencies.append({k: entry[k] for k in ('file_id', 'content_hash', 'name') if k in entry})
                            for resource in entry.get('resources', []):
                                dependencies.append({**resource['definition']['source'],
                                    'lookup_key': resource['name'], 'scope': resource['project_id']})
                        save_context_dependencies(store, workspace, run_id, unit.unit_id, dependencies)
                        save_unit_result(store,workspace,run_id,unit.unit_id,file_id=unit.file_id,
                            content_hash=unit.content_hash,start_char=unit.start_offset,end_char=unit.end_offset,
                            context_hash=_unit_context_hash(prepared,plan,execution,unit,expected_revision),status='planned',
                            result={'unit_spec':unit.model_dump(exclude={'code'})})
            local_results, config, local_counts = prepare_analysis_results(store, workspace,
                request.file_ids, request.force_parser, cancelled=cancelled)
        execution.check()
        update(.1, 'Local extraction complete')
        selected = {s.file_id for s in prepared.sources}
        parser = {m['file_id']: p for m, p in local_results}
        rebuilt = {fid: ParseResult(diagnostics=list(p.diagnostics), metadata=dict(p.metadata))
                   for fid, p in parser.items() if fid in selected}
        for fid, output in rebuilt.items():
            if output.metadata.get('source_kind') == 'dbt':
                output.assets = list(parser[fid].assets)
        sources = {s.file_id: s for s in prepared.sources}
        counts['units'] = len(plan.units)
        claims = []
        source_groups = {}
        original_indexes = {fid: {} for fid in selected}
        stage = 'extracting'
        save_run(store, workspace, run_id, mode=request.mode, status=stage)
        from dataforge.ai_reconciliation import reconcile_candidates
        from dataforge.ai_validation import operation_contexts, validate_project_response

        # Use the established single-request path when the user selects one worker
        # and one file. Auto scales up after three initial singleton units.
        optimized = ((request.max_parallel_requests or 1) > 1 or (request.max_files_per_request or 1) > 1
                     or (request.max_files_per_request is None and len(plan.units) > 3))
        if optimized:
            from dataforge.ai_scheduler import run_pending_requests
            hashes = {u.unit_id: _unit_context_hash(prepared, plan, execution, u, expected_revision) for u in plan.units}
            pending = tuple(u for u in plan.units if not load_validation_checkpoint(store, workspace, run_id, u, hashes[u.unit_id])
                and (request.refresh_ai or (_cached(store, workspace, u, hashes[u.unit_id]) is None
                    and _prior_checkpoint(store, workspace, u, hashes[u.unit_id], request) is None)))
            def accept_item(unit, response, record_id):
                settings = dict(config)
                from dataforge.services import source_dialect
                metadata = next(m for m, _ in local_results if m['file_id'] == unit.file_id)
                settings['dialect'] = source_dialect(metadata, config)
                context = ValidationContext(unit=unit, workspace_id=workspace, source_text=sources[unit.file_id].code,
                    settings=settings, catalog=plan.context_for(unit), parser_result=parser[unit.file_id])
                validated = validate_project_response(response, context)
                cacheable = (not validated.rejected and not validated.unresolved
                             and validated.coverage.status in {'complete', 'no_operations'})
                save_validation_checkpoint(store, workspace, run_id, unit, hashes[unit.unit_id], validated,
                    reviewed=not request.additional_ai_review, record_id=record_id,
                    cache={'wire_version': 2, 'payload': encode_project_result(response)} if cacheable else None,
                    transaction=False)
            def record_usage(outcome):
                nonlocal usage_known
                from types import SimpleNamespace
                _usage(counts, SimpleNamespace(usage=outcome.usage))
                usage_known &= bool(outcome.metadata.get('usage_known')) and not outcome.error
                save_run(store, workspace, run_id, mode=request.mode, status='extracting',
                    summary={'counts': {**dict(counts), 'requests': execution.prior_requests + execution.attempts,
                        'reserved_output_tokens': execution.prior_reserved + execution.reserved_output_tokens},
                        'usage_known': usage_known})
            try:
                if pending:
                    run_pending_requests(store, workspace, run_id, pending, execution,
                        contexts={u.unit_id: plan.context_for(u) for u in pending}, accept=accept_item,
                        progress=progress, record_usage=record_usage)
            except TimeoutError as exc:
                if str(exc) not in {'execution_budget_reached', 'project_allowance_reached'}:
                    raise
                execution.pause_reason = str(exc)
                return _pause(store, workspace, run_id, request, execution, counts, usage_known)

        for index, unit in enumerate(plan.units):
            execution.check()
            _current(store, workspace, prepared, expected_revision)
            execution.catalog = plan.context_for(unit)
            context_hash = _unit_context_hash(prepared, plan, execution, unit, expected_revision)
            settings = dict(config)
            from dataforge.services import source_dialect
            metadata = next(m for m, _ in local_results if m['file_id'] == unit.file_id)
            settings['dialect'] = source_dialect(metadata, config)
            context = ValidationContext(unit=unit, workspace_id=workspace,
                source_text=sources[unit.file_id].code, settings=settings, catalog=execution.catalog,
                parser_result=parser[unit.file_id])
            checkpoint = load_validation_checkpoint(store, workspace, run_id, unit, context_hash)
            if not checkpoint and not request.refresh_ai:
                checkpoint = _prior_checkpoint(store, workspace, unit, context_hash, request)
                if checkpoint:
                    counts['cache_hits'] += 1
                    saved, saved_reviewed, saved_record, saved_cache = checkpoint
                    save_validation_checkpoint(store, workspace, run_id, unit, context_hash, saved,
                        reviewed=saved_reviewed, record_id=saved_record, cache=saved_cache)
            record_id, reviewed, cache = None, False, None
            if checkpoint:
                validated, reviewed, record_id, cache = checkpoint
            else:
                response = None if request.refresh_ai else _cached(store, workspace, unit, context_hash)
                if response is not None:
                    counts['cache_hits'] += 1
                else:
                    if not _stage_ready(store,workspace,unit,'project_lineage',execution):
                        return _pause(store,workspace,run_id,request,execution,counts,usage_known)
                    _set_inflight_callback(store, workspace, run_id, request, execution, counts, unit, 'project_lineage')
                    update(.1 + .75 * index / max(1, len(plan.units)), 'Waiting for AI extraction response')
                    result = invoke_analysis_unit(store, workspace, unit, 'project_lineage', execution)
                    update(.1 + .75 * index / max(1, len(plan.units)), 'Validating AI extraction response')
                    if result is None or result.outcome != 'validated' or result.result is None:
                        raise ValueError('incomplete_ai_response')
                    response, record_id = result.result, result.record_id or None
                    usage_known &= result.usage_known
                    _usage(counts, result)
                validated = validate_project_response(response, context)
                cacheable = (not validated.rejected and not validated.unresolved
                             and validated.coverage.status in {'complete', 'no_operations'})
                cache = {'wire_version': 2, 'payload': encode_project_result(response)} if cacheable else None
                reviewed = not request.additional_ai_review
                save_validation_checkpoint(store, workspace, run_id, unit, context_hash, validated,
                    reviewed=reviewed, record_id=record_id, cache=cache)
                _clear_inflight(store, workspace, run_id, request, execution, counts, usage_known)
            from dataforge.ai_resolution import apply_resolution, plan_resolution
            resolution = plan_resolution(validated)
            while resolution:
                stage = 'resolving'
                execution.resolution_context = resolution
                trial = preview_analysis_routes(store, workspace, [unit], execution, tasks=['project_lineage'])
                if any(not b['reason'].startswith('worst_case_') for b in trial['blocked']):
                    validated.resolution_done = True
                    break
                if not _stage_ready(store, workspace, unit, 'project_lineage', execution):
                    return _pause(store, workspace, run_id, request, execution, counts, usage_known)
                _set_inflight_callback(store, workspace, run_id, request, execution, counts, unit, 'project_lineage')
                update(.1 + .75 * index / max(1, len(plan.units)), 'Resolving targeted source uncertainty')
                result = invoke_analysis_unit(store, workspace, unit, 'project_lineage', execution)
                if result is None or result.outcome != 'validated' or result.result is None:
                    raise ValueError('incomplete_resolution_response')
                usage_known &= result.usage_known
                _usage(counts, result)
                validated, _ = apply_resolution(validated, validate_project_response(result.result, context))
                counts['resolution_rounds'] += 1
                cache = None
                save_validation_checkpoint(store, workspace, run_id, unit, context_hash, validated,
                    reviewed=reviewed, record_id=record_id, cache=cache)
                _clear_inflight(store, workspace, run_id, request, execution, counts, usage_known)
                resolution = plan_resolution(validated)
            execution.resolution_context = None
            if unit.source_focus:
                # Recompose every union after component review. A rejected component
                # must invalidate a union saved by an earlier, unreviewed build.
                validated.accepted = [f for f in validated.accepted if not f.detail.get('source_view_units')]
            parser_indexes = {id(op): i for i, op in enumerate(parser[unit.file_id].operations)}
            original_indexes[unit.file_id].update({key: parser_indexes[id(op)]
                for op, _, _, key in operation_contexts(context, parser[unit.file_id], scoped=False)})
            # Generic views validate against the full original, but comparing every
            # whole-block parser fact per view is quadratic. Reconcile each parent once below.
            reconciled = reconcile_candidates([] if unit.source_focus else parser[unit.file_id], validated,
                'ai' if unit.source_focus else request.mode, context=context)
            candidates = [f for f in reconciled.facts if f.origin == 'ai']
            if unit.source_focus:
                from dataforge.ai_composition import review_facts
                candidates = review_facts(validated, unit)
            if request.additional_ai_review and candidates and not reviewed:
                stage='reviewing'
                remaining=[f for f in candidates if f.candidate_id not in validated.reviewed_candidates]
                for batch in review_batches(remaining, unit=unit, settings=settings):
                    execution.review_candidates=batch
                    if not _stage_ready(store,workspace,unit,'lineage_review',execution):
                        return _pause(store,workspace,run_id,request,execution,counts,usage_known)
                    _set_inflight_callback(store,workspace,run_id,request,execution,counts,unit,'lineage_review')
                    update(.1 + .75 * index / max(1, len(plan.units)), 'Waiting for AI review response')
                    review=invoke_analysis_unit(store,workspace,unit,'lineage_review',execution)
                    update(.1 + .75 * index / max(1, len(plan.units)), 'Validating AI review response')
                    if review is None or review.outcome!='validated' or review.result is None:
                        raise ValueError('incomplete_ai_review')
                    usage_known &= review.usage_known
                    _usage(counts,review)
                    review.result.assert_candidates({c['candidate_id'] for c in batch})
                    rejected_ids=set()
                    for decision in review.result.decisions:
                        if decision.decision!='supported' or not decision.evidence:
                            rejected_ids.add(decision.candidate_id)
                            validated.unresolved.append(ClaimDecision(candidate_id=decision.candidate_id,
                                reason='additional_ai_review_insufficient',status='unresolved'))
                    validated.accepted=[f for f in validated.accepted if f.candidate_id not in rejected_ids]
                    if unit.source_focus:
                        from dataforge.ai_composition import retain_reviewed_fragments
                        retain_reviewed_fragments(validated, rejected_ids)
                    validated.reviewed_candidates.extend(c['candidate_id'] for c in batch)
                    counts['review_batches'] += 1
                    save_validation_checkpoint(store,workspace,run_id,unit,context_hash,validated,
                        reviewed=False,record_id=record_id,cache=cache)
                    _clear_inflight(store,workspace,run_id,request,execution,counts,usage_known)
                execution.review_candidates=[]
                reconciled=reconcile_candidates([] if unit.source_focus else parser[unit.file_id], validated,
                    'ai' if unit.source_focus else request.mode, context=context)
            if not reviewed:
                save_validation_checkpoint(store,workspace,run_id,unit,context_hash,validated,
                    reviewed=True,record_id=record_id,cache=cache)
                _clear_inflight(store,workspace,run_id,request,execution,counts,usage_known)
            if unit.source_focus:
                source_groups.setdefault((unit.file_id, unit.source_focus.parent_id), []).append(
                    (unit, context, validated, context_hash, record_id))
            output = rebuilt[unit.file_id]
            if not unit.source_focus:
                output.operations.extend(reconciled.operations)
                output.assets.extend(reconciled.assets)
            counts['accepted'] += len(validated.accepted)
            counts['rejected'] += len(validated.rejected)
            counts['unresolved'] += len(validated.unresolved)
            counts['conflicts'] += len(reconciled.conflicts)
            for name in ('agreed', 'parser_only', 'ai_only', 'omissions'):
                counts[name] += reconciled.counts.get(name, 0)
            if (validated.coverage.status not in {'complete', 'no_operations'} or reconciled.conflicts
                    or validated.unresolved or validated.rejected):
                counts['coverage_gaps'] += 1
            final_candidates = {f.candidate_id: f for f in reconciled.facts if f.candidate_id}
            for fact in validated.accepted:
                fact = final_candidates.get(fact.candidate_id, fact)
                claims.append({'claim_id': fact.candidate_id, 'unit_id': unit.unit_id, 'kind': fact.kind,
                    'status': 'unresolved' if fact.status == 'unresolved' else 'accepted',
                    'payload': fact.model_dump(exclude={'detail'}), 'record_id': record_id, 'reasons': []})
            for ordinal, fact in enumerate(reconciled.parser_only):
                claims.append({'claim_id': stable_id(unit.unit_id, 'parser', str(ordinal)),
                    'unit_id': unit.unit_id, 'kind': fact.kind,
                    'status': 'parser_only', 'payload': fact.model_dump(exclude={'detail'}), 'reasons': ['ai_omission']})
            for decision in [*validated.rejected, *validated.unresolved]:
                claims.append({'claim_id': decision.candidate_id or stable_id(unit.unit_id, decision.reason),
                    'unit_id': unit.unit_id, 'kind': 'decision', 'status': decision.status,
                    'payload': {}, 'reasons': [decision.reason]})
            counts['processed'] += 1
            update(.1 + .75 * (index + 1) / max(1, len(plan.units)), 'AI extraction and evidence checks')
        for (fid, parent_id), entries in source_groups.items():
            from dataforge.ai_analysis_models import EvidenceCitation, ValidationReport
            from dataforge.ai_composition import compose_fragments
            first, context, validated, context_hash, record_id = min(entries, key=lambda item: (
                item[0].source_focus.start_offset, item[0].source_focus.context_start, item[0].unit_id))
            parent = first.model_copy(update={'unit_id': parent_id, 'source_focus': None})
            original_context = context.model_copy(update={'unit': parent})
            composed = compose_fragments([entry[2] for entry in entries], original_context)
            existing = {fact.candidate_id for entry in entries for fact in entry[2].accepted}
            added = [fact for fact in composed.accepted if fact.candidate_id not in existing]
            for fact in added:
                fact.unit_id = first.unit_id
                fact.evidence = EvidenceCitation.from_unit(first)
            validated.accepted.extend(added)
            if request.additional_ai_review:
                validated.reviewed_candidates.extend(f.candidate_id for f in added)
            validated.rejected.extend(composed.rejected)
            validated.unresolved.extend(composed.unresolved)
            save_validation_checkpoint(store, workspace, run_id, first, context_hash, validated,
                reviewed=True, record_id=record_id, cache=None)
            combined = ValidationReport(accepted=[f for entry in entries for f in entry[2].accepted],
                assets=[asset for entry in entries for asset in entry[2].assets])
            final = reconcile_candidates(parser[fid], combined, request.mode, context=original_context)
            rebuilt[fid].operations.extend(final.operations)
            rebuilt[fid].assets.extend(final.assets)
            counts['accepted'] += len(added)
            counts['rejected'] += len(composed.rejected)
            counts['unresolved'] += len(composed.unresolved)
            for fact in added:
                claims.append({'claim_id': fact.candidate_id, 'unit_id': first.unit_id, 'kind': fact.kind,
                    'status': 'accepted', 'payload': fact.model_dump(exclude={'detail'}), 'record_id': record_id, 'reasons': []})
            for name in ('agreed', 'parser_only', 'omissions'):
                counts[name] += final.counts.get(name, 0)
            for ordinal, fact in enumerate(final.parser_only):
                claims.append({'claim_id': stable_id(parent_id, 'parser', str(ordinal)),
                    'unit_id': first.unit_id, 'kind': fact.kind, 'status': 'parser_only',
                    'payload': fact.model_dump(exclude={'detail'}), 'reasons': ['ai_omission']})
        from dataforge.ai_semantic import merge_publication_operations
        for output in rebuilt.values():
            output.operations = merge_publication_operations(output.operations)
        # CSV continues to provide local metadata; unselected files retain their
        # committed representation, including valid accepted AI contributions.
        for fid, output in rebuilt.items():
            remapped = []
            for index, op in enumerate(output.operations):
                old_index = original_indexes[fid].get(op.evidence_key)
                remapped.extend({**record, 'operation_index': index}
                    for record in parser[fid].metadata.get('declared_schemas', [])
                    if record.get('operation_index') == old_index)
            output.metadata['declared_schemas'] = remapped
        results = [(m, rebuilt[m['file_id']] if m['file_id'] in rebuilt and m['extension'] != '.csv' else p)
                   for m, p in local_results]
        restore_manual_ai_results(store, workspace, results, config)
        stage = 'linking'
        update(.9, 'Linking saved table and column facts')
        from dataforge.ai_linking import compose_dbt_publication, link_stored_facts, load_link_snapshot
        from dataforge.ai_pipeline_store import save_link_checkpoint
        link_hashes = {u.unit_id: _unit_context_hash(prepared, plan, execution, u, expected_revision) for u in plan.units}
        linked = link_stored_facts(load_link_snapshot(store, workspace, run_id, plan.units, link_hashes),
                                  case_sensitive=config.get('case_sensitive', False))
        save_link_checkpoint(store, workspace, run_id, linked['fingerprint'], linked)
        counts['link_conflicts'] = len(linked['unresolved'])
        counts['coverage_gaps'] += len(linked['unresolved'])
        local_counts['dbt_projects'] = compose_dbt_publication(local_counts.get('dbt_projects', []), results, mode=request.mode)
        stage = 'ready'
        execution.check()
        counts['requests'] = execution.prior_requests + execution.attempts
        counts['reserved_output_tokens'] = execution.prior_reserved + execution.reserved_output_tokens
        if not counts['requests']:
            usage_known = False
        report = AnalysisReport(run_id=run_id, mode=request.mode, status='committed',
            complete=not counts['coverage_gaps'], counts=dict(counts), usage_known=usage_known,
            reasons=['semantic_coverage_incomplete'] if counts['coverage_gaps'] else [])
        with store.analysis_lock, store.transaction():
            execution.check()
            _current(store, workspace, prepared, expected_revision, full=True)
            published = publish_analysis_results(store, workspace, results, config, local_counts,
                                                 cancelled=cancelled)
            report.counts.update({k: published[k] for k in ('analyzed', 'cached', 'assets', 'edges')})
            save_claim_decisions(store, workspace, run_id, claims)
            attach_published_support(store, workspace, run_id, results, claims)
            save_run(store, workspace, run_id, mode=request.mode, status='committed',
                analysis_run_id=published['run_id'], accepted_results=results,
                configuration={**config, **({'dbt': prepared.settings['dbt']} if 'dbt' in prepared.settings else {})},
                summary=report.model_dump())
        update(1., 'Publication complete')
        return report
    except (ValueError, OSError, TimeoutError, InterruptedError) as exc:
        reason = 'cancelled' if isinstance(exc, InterruptedError) else str(exc)
        if isinstance(exc, TimeoutError) and reason not in {'project_allowance_reached',
                'provider_daily_quota_exhausted', 'provider_credits_exhausted',
                'unknown_inflight_request_requires_explicit_retry'}:
            reason = 'deadline_exceeded'
        reason = manager.redact(reason)[:500]
        status = 'awaiting_continuation' if isinstance(exc, TimeoutError) and registered else 'cancelled' if isinstance(exc, InterruptedError) else (
            'stale' if reason == 'source_or_configuration_changed' else 'blocked' if not registered else 'failed')
        if execution:
            counts['requests'] = getattr(execution, 'prior_requests', 0) + execution.attempts
            counts['reserved_output_tokens'] = getattr(execution, 'prior_reserved', 0) + execution.reserved_output_tokens
        report = AnalysisReport(run_id=run_id, mode=request.mode, status=status, counts=dict(counts),
            usage_known=False, reasons=[reason])
        if request.resume_run_id and not registered:
            # A busy/blocked probe must never mutate another execution's active run.
            if status != 'stale':
                return report
            prior = store.rows('SELECT summary FROM ai_analysis_runs WHERE workspace_id=? AND run_id=?', [workspace, run_id])
            if prior:
                report.counts = json.loads(prior[0]['summary']).get('counts', {})
        save_run(store, workspace, run_id, mode=request.mode, status=status,
                 summary={**report.model_dump(), 'stage': stage})
        return report
    except Exception:
        # A programming/driver failure must not leave a durable busy guard forever.
        save_run(store, workspace, run_id, mode=request.mode, status='failed',
                 summary={'reasons': ['internal_error'], 'stage': stage})
        raise


def analysis_report(store, workspace, run_id=None, *, include_source=False):
    """Bounded callers paginate claims; source permission controls candidate details."""
    report = load_analysis_report(store, workspace, run_id, include_source=include_source)
    if report is None:
        raise ValueError('Analysis report not found')
    report.pop('configuration', None)
    for claim in report['claims']:
        if not include_source:
            claim.pop('payload', None)
    return report


def _protocol_hash():
    from dataforge.llm import PROMPTS
    return _hash({'semantic_planning': 5, 'component_composition': 2, 'review_batching': 3,
        'resolution': (PROMPTS / 'project_resolution' / 'system.md').read_text(encoding='utf-8'),
        'source_handlers': {kind: analysis_prompt_hash('project_lineage', source_kind=kind) for kind in ('sql', 'sas', 'dbt')},
        'validator': VALIDATOR_VERSION, 'parser': PARSER_VERSION,
        'prompts':{task:{'complete':analysis_prompt_hash(task),'focused':analysis_prompt_hash(task,focused=True)}
            for task in ('project_lineage','lineage_review')}})


def _clear_inflight(store, workspace, run_id, request, execution, counts, usage_known):
    snapshot = dict(counts)
    snapshot['requests'] = execution.prior_requests + execution.attempts
    snapshot['reserved_output_tokens'] = execution.prior_reserved + execution.reserved_output_tokens
    save_run(store, workspace, run_id, mode=request.mode, status='extracting',
        summary={'counts': snapshot, 'usage_known': usage_known, 'inflight': False})


def _set_inflight_callback(store, workspace, run_id, request, execution, counts, unit, task):
    execution.journal_wait = lambda until: save_run(store, workspace, run_id, mode=request.mode,
        status='waiting_provider', summary={'wait_until': until, 'active_seconds': execution.active_seconds})
    def journal():
        snapshot = dict(counts)
        snapshot['requests'] = execution.prior_requests + execution.attempts
        snapshot['reserved_output_tokens'] = execution.prior_reserved + execution.reserved_output_tokens
        save_run(store, workspace, run_id, mode=request.mode, status='extracting',
            summary={'counts': snapshot, 'inflight': {'unit_id': unit.unit_id, 'task': task,
                'candidate_ids': [c['candidate_id'] for c in execution.review_candidates] if task=='lineage_review' else []}})
    execution.journal_attempt = journal


def _stage_ready(store,workspace,unit,task,execution):
    preview=preview_analysis_routes(store,workspace,[unit],execution,tasks=[task])
    blocked=[b['reason'] for b in preview['blocked'] if not b['reason'].startswith('worst_case_')]
    if blocked:
        raise ValueError('stage_preflight_blocked: '+', '.join(sorted(set(blocked))))
    attempts=max(execution.attempts,getattr(execution,'stage_attempts',0))+preview['max_provider_attempts']
    tokens=max(execution.reserved_output_tokens,getattr(execution,'stage_tokens',0))+preview['max_output_tokens_reserved']
    execution.check()
    allowance = getattr(execution, 'project_allowance', None)
    if allowance and (execution.prior_requests + attempts > allowance['max_provider_attempts']
            or execution.prior_reserved + tokens > allowance['max_output_tokens_total']):
        execution.pause_reason = 'project_allowance_reached'
        return False
    if attempts>execution.request.max_provider_attempts or tokens>execution.request.max_output_tokens_total:
        if not execution.request.auto_continue:
            return False
        execution.rollover()
        attempts, tokens = preview['max_provider_attempts'], preview['max_output_tokens_reserved']
    execution.stage_attempts,execution.stage_tokens=attempts,tokens
    return True


def _pause(store, workspace, run_id, request, execution, counts, usage_known):
    counts['requests'] = execution.prior_requests + execution.attempts
    counts['reserved_output_tokens'] = execution.prior_reserved + execution.reserved_output_tokens
    counts['checkpointed'] = store.rows("SELECT count(*) AS n FROM ai_analysis_units WHERE workspace_id=? AND run_id=? AND status IN ('validated','staged')", [workspace, run_id])[0]['n']
    counts['remaining'] = counts['units'] - counts['checkpointed']
    report = AnalysisReport(run_id=run_id, mode=request.mode, status='awaiting_continuation',
        counts=dict(counts), usage_known=usage_known,
        reasons=[getattr(execution, 'pause_reason', 'execution_budget_reached')])
    save_run(store, workspace, run_id, mode=request.mode, status=report.status,
        summary={**report.model_dump(), 'active_seconds': execution.active_seconds})
    return report
