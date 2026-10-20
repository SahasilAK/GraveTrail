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
from dataforge.ai_budget import execution_budget
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


def _prepare(store, workspace, request, connections=None, cancelled=None, transport=None, authorize=None):
    try:
        prepared = prepare_analysis(store, workspace, request)
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
    plan = plan_ai_units(prepared, max_chars=200000)
    execution = AIExecutionContext(request, connections=connections or current_connections(),
        cancelled=cancelled, transport=transport, settings=prepared.settings, authorize=authorize,
        source_hashes={s.file_id: s.content_hash for s in prepared.sources})
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
            capacity={'complete_prompt_exceeds_context_budget','complete_prompt_exceeds_model_capacity'}
            if (projection_count(unit,unit_dialect(unit,prepared.settings))>100
                    or any(b['reason'] in capacity for b in trial['blocked'])):
                parts=split_projection_unit(unit,unit_dialect(unit,prepared.settings)) or split_proc_sql_unit(unit)
                if parts:
                    return [page for part in parts for page in fit(part)]
            return [unit]
        plan=replace(plan,units=tuple(page for unit in plan.units for page in fit(unit)))
    plan=replace(plan,context_hash=_hash({'context':plan.context_hash,
        'partitions':[(u.unit_id,u.focus.model_dump() if u.focus else None) for u in plan.units]}))
    blocked, routes, bundles, allowances, excluded = list(plan.blocked), {}, [], [], []
    reusable, ends, review_provisional = 0, [], False
    expected = _state_revision(store, workspace)
    for unit in plan.units:
        execution.catalog = plan.context_for(unit)
        execution.review_candidates = []
        context_hash = _unit_context_hash(prepared, plan, execution, unit, expected)
        checkpoint = load_validation_checkpoint(store, workspace, request.resume_run_id, unit, context_hash) if request.resume_run_id else None
        cached = None if request.refresh_ai else _cached(store, workspace, unit, context_hash)
        tasks=[]
        if not checkpoint and cached is None:
            tasks.append(('project_lineage',[]))
        else:
            reusable += 1
        if request.additional_ai_review and not (checkpoint and checkpoint[1]):
            if checkpoint:
                from dataforge.ai_analysis_models import ValidationContext
                from dataforge.ai_reconciliation import reconcile_candidates
                from dataforge.ai_semantic import unit_dialect
                from dataforge.parsers.sas import parse_sas
                from dataforge.parsers.sql import parse_sql
                source=next(source for source in prepared.sources if source.file_id==unit.file_id)
                settings={**prepared.settings,'dialect':unit_dialect(unit,prepared.settings)}
                parsed=(parse_sql(source.code,settings['dialect']) if unit.extension=='.sql' else
                    parse_sas(source.code,settings.get('library_mappings'),settings.get('macros'),settings['dialect']))
                context=ValidationContext(unit=unit,workspace_id=workspace,source_text=source.code,
                    settings=settings,catalog=execution.catalog,parser_result=parsed)
                facts=[f for f in reconcile_candidates(parsed,checkpoint[0],request.mode,context=context).facts
                    if f.origin=='ai' and f.candidate_id not in checkpoint[0].reviewed_candidates]
                tasks.extend(('lineage_review',batch) for batch in review_batches(facts))
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
    execution.review_candidates=[]
    budget=execution_budget(bundles,**{k:getattr(request,k) for k in
        ('max_provider_attempts','max_output_tokens_total','max_seconds')})
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
    return prepared,plan,execution,{'valid':not blocked,'mode':request.mode,
        'files':len(prepared.sources),'units':len(plan.units),'empty_files':len(plan.empty_files),
        'blocked':blocked,'routes':routes,'disclosure':list(plan.disclosure),
        'allowances':allowances,'excluded_routes':excluded,'reusable_units':reusable,**budget,
        'review_sizing_provisional':review_provisional,
        'semantic_pages':sum(u.focus is not None for u in plan.units),
        'estimated_characters':plan.estimated_characters,'max_provider_attempts':budget['total_attempts'],
        'max_output_tokens_reserved':budget['total_output_tokens'],'manifest_hash':prepared.manifest_hash}


def preview_analysis(store, workspace, request, *, connections=None):
    """Offline disclosure/context/budget preview; no connection tests or requests."""
    request = _resume_request(store, workspace, AnalysisRequest.model_validate(request))
    if request.mode == 'parser':
        return {'valid': True, 'mode': 'parser', 'files': len(store.files(workspace)),
                'units': 0, 'blocked': [], 'routes': {}, 'max_provider_attempts': 0}
    return _prepare(store, workspace, request, connections)[3]


def _current(store, workspace, prepared, expected_revision):
    current = prepare_analysis(store, workspace, prepared.request)
    if (current.manifest_hash != prepared.manifest_hash or current.prior_revision != prepared.prior_revision
            or _state_revision(store, workspace) != expected_revision):
        raise ValueError('source_or_configuration_changed')


def _unit_context_hash(prepared, plan, execution, unit, expected_revision):
    prompt_hash = analysis_prompt_hash('project_lineage',focused=bool(unit.focus))
    return _hash({'manifest': prepared.manifest_hash, 'context': plan.context_hash,
        'prompt': prompt_hash, 'settings_revision': expected_revision,
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
    return AnalysisRequest.model_validate({**saved, **{k: getattr(request, k) for k in
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


def run_analysis(store, workspace, request, *, connections=None, authorize=None,
                 progress=None, cancelled=None, transport=None):
    """Run only under an explicit user action; failures retain the prior graph."""
    request = AnalysisRequest.model_validate(request)
    manager = connections or current_connections()
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
                if prior_summary.get('inflight') and not request.retry_unknown:
                    return AnalysisReport(run_id=run_id, mode=request.mode, status='awaiting_continuation',
                        reasons=['unknown_inflight_request_requires_explicit_retry'])
            execution.prior_requests = prior_summary.get('counts', {}).get('requests', 0)
            execution.prior_reserved = prior_summary.get('counts', {}).get('reserved_output_tokens', 0)
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
                                    'reserved_output_tokens': execution.prior_reserved}, 'inflight': False})
            registered = True
            if not request.resume_run_id:
                with store.transaction():
                    for unit in plan.units:
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
        sources = {s.file_id: s for s in prepared.sources}
        counts['units'] = len(plan.units)
        claims = []
        original_indexes = {fid: {} for fid in selected}
        stage = 'extracting'
        save_run(store, workspace, run_id, mode=request.mode, status=stage)
        from dataforge.ai_reconciliation import reconcile_candidates
        from dataforge.ai_validation import operation_contexts, validate_project_response

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
                    result = invoke_analysis_unit(store, workspace, unit, 'project_lineage', execution)
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
            parser_indexes = {id(op): i for i, op in enumerate(parser[unit.file_id].operations)}
            original_indexes[unit.file_id].update({key: parser_indexes[id(op)]
                for op, _, _, key in operation_contexts(context, parser[unit.file_id], scoped=False)})
            reconciled = reconcile_candidates(parser[unit.file_id], validated, request.mode, context=context)
            candidates = [f for f in reconciled.facts if f.origin == 'ai']
            if request.additional_ai_review and candidates and not reviewed:
                stage='reviewing'
                remaining=[f for f in candidates if f.candidate_id not in validated.reviewed_candidates]
                for batch in review_batches(remaining):
                    execution.review_candidates=batch
                    if not _stage_ready(store,workspace,unit,'lineage_review',execution):
                        return _pause(store,workspace,run_id,request,execution,counts,usage_known)
                    _set_inflight_callback(store,workspace,run_id,request,execution,counts,unit,'lineage_review')
                    review=invoke_analysis_unit(store,workspace,unit,'lineage_review',execution)
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
                    validated.reviewed_candidates.extend(c['candidate_id'] for c in batch)
                    counts['review_batches'] += 1
                    save_validation_checkpoint(store,workspace,run_id,unit,context_hash,validated,
                        reviewed=False,record_id=record_id,cache=cache)
                    _clear_inflight(store,workspace,run_id,request,execution,counts,usage_known)
                execution.review_candidates=[]
                reconciled=reconcile_candidates(parser[unit.file_id],validated,request.mode,context=context)
            if not reviewed:
                save_validation_checkpoint(store,workspace,run_id,unit,context_hash,validated,
                    reviewed=True,record_id=record_id,cache=cache)
                _clear_inflight(store,workspace,run_id,request,execution,counts,usage_known)
            output = rebuilt[unit.file_id]
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
            _current(store, workspace, prepared, expected_revision)
            published = publish_analysis_results(store, workspace, results, config, local_counts,
                                                 cancelled=cancelled)
            report.counts.update({k: published[k] for k in ('analyzed', 'cached', 'assets', 'edges')})
            save_claim_decisions(store, workspace, run_id, claims)
            attach_published_support(store, workspace, run_id, results, claims)
            save_run(store, workspace, run_id, mode=request.mode, status='committed',
                analysis_run_id=published['run_id'], accepted_results=results, configuration=config,
                summary=report.model_dump())
        update(1., 'Publication complete')
        return report
    except (ValueError, OSError, TimeoutError, InterruptedError) as exc:
        reason = 'cancelled' if isinstance(exc, InterruptedError) else (
            'deadline_exceeded' if isinstance(exc, TimeoutError) else str(exc))
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
    return _hash({'semantic_planning': 1, 'review_batching': 1,
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
    if attempts>execution.request.max_provider_attempts or tokens>execution.request.max_output_tokens_total:
        return False
    execution.stage_attempts,execution.stage_tokens=attempts,tokens
    return True


def _pause(store, workspace, run_id, request, execution, counts, usage_known):
    counts['requests'] = execution.prior_requests + execution.attempts
    counts['reserved_output_tokens'] = execution.prior_reserved + execution.reserved_output_tokens
    counts['remaining'] = counts['units'] - counts['processed']
    report = AnalysisReport(run_id=run_id, mode=request.mode, status='awaiting_continuation',
        counts=dict(counts), usage_known=usage_known, reasons=['execution_budget_reached'])
    save_run(store, workspace, run_id, mode=request.mode, status=report.status, summary=report.model_dump())
    return report


def apply_context_allowance(store, workspace, request, required, expected_revision):
    """Explicit local action: raise only calculated disclosure/context caps, under CAS."""
    from dataforge.llm import Profile
    from dataforge.settings_service import check_revision
    request = AnalysisRequest.model_validate(request)
    with store.analysis_lock, store.transaction():
        check_revision(store, workspace, expected_revision)
        preview = preview_analysis(store, workspace, request)
        actual = max((a['required_characters'] for a in preview.get('allowances', []) if not a['valid']), default=0)
        if type(required) is not int or required != actual or not 500 <= required <= 100000:
            raise ValueError('Calculated context allowance changed or exceeds the application limit')
        store.set_setting(workspace, 'max_context_chars', max(required, store.setting(workspace, 'max_context_chars', 8000)))
        profile_ids = {a['profile_id'] for a in preview['allowances']
                       if 'complete_prompt_exceeds_context_budget' in a['reasons']}
        for pid in profile_ids:
            row = store.rows('SELECT config FROM llm_profiles WHERE workspace_id=? AND profile_id=?', [workspace, pid])[0]
            profile = Profile.model_validate_json(row['config'])
            profile.context_chars = max(required, profile.context_chars)
            profile.context_mode = 'custom'
            store.execute('UPDATE llm_profiles SET config=? WHERE workspace_id=? AND profile_id=?',
                [profile.model_dump_json(), workspace, pid])
    return preview_analysis(store, workspace, request)
