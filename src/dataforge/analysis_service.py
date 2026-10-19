"""Explicit, staged AI project builds shared by the UI, CLI and MCP.

Provider work never owns a database transaction. Publication rechecks the original
inventory/configuration/revision and commits accepted table/column facts together.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter

from dataforge.ai_analysis_models import (
    AnalysisReport,
    AnalysisRequest,
    ClaimDecision,
    ProjectLineageResponse,
    ValidationContext,
)
from dataforge.ai_analysis_store import (
    active_project_runs,
    attach_published_support,
    inherited_context_sources,
    load_analysis_report,
    save_claim_decisions,
    save_run,
    save_unit_result,
)
from dataforge.ai_context import AIExecutionContext, plan_ai_units, prepare_analysis
from dataforge.connections import current_connections
from dataforge.llm import (
    analysis_prompt,
    invoke_analysis_unit,
    preview_analysis_routes,
    review_payload,
)
from dataforge.models import ParseResult, stable_id
from dataforge.services import (
    analyze,
    prepare_analysis_results,
    publish_analysis_results,
    restore_manual_ai_results,
)
from dataforge.settings_service import revision

VALIDATOR_VERSION = '1'


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
    prepared = prepare_analysis(store, workspace, request)
    plan = plan_ai_units(prepared, max_chars=min(store.setting(workspace, 'llm_chunk_chars', 4000),
                                               store.setting(workspace, 'max_context_chars', 8000)))
    execution = AIExecutionContext(request, connections=connections or current_connections(),
        cancelled=cancelled, transport=transport, settings=prepared.settings, authorize=authorize,
        source_hashes={s.file_id: s.content_hash for s in prepared.sources})
    blocked, routes, attempts, tokens = list(plan.blocked), {}, 0, 0
    for unit in plan.units:
        execution.catalog = plan.context_for(unit)
        preview = preview_analysis_routes(store, workspace, [unit], execution)
        blocked.extend(preview['blocked'])
        routes.update(preview['routes'])
        attempts += preview['max_provider_attempts']
        tokens += preview['max_output_tokens_reserved']
    if attempts > request.max_provider_attempts:
        blocked.append({'reason': 'worst_case_provider_attempt_budget'})
    if tokens > request.max_output_tokens_total:
        blocked.append({'reason': 'worst_case_output_reservation_budget'})
    return prepared, plan, execution, {'valid': not blocked, 'mode': request.mode,
        'files': len(prepared.sources), 'units': len(plan.units), 'empty_files': len(plan.empty_files),
        'blocked': blocked, 'routes': routes, 'disclosure': list(plan.disclosure),
        'estimated_characters': plan.estimated_characters, 'max_provider_attempts': attempts,
        'max_output_tokens_reserved': tokens, 'manifest_hash': prepared.manifest_hash}


def preview_analysis(store, workspace, request, *, connections=None):
    """Offline disclosure/context/budget preview; no connection tests or requests."""
    request = AnalysisRequest.model_validate(request)
    if request.mode == 'parser':
        return {'valid': True, 'mode': 'parser', 'files': len(store.files(workspace)),
                'units': 0, 'blocked': [], 'routes': {}, 'max_provider_attempts': 0}
    return _prepare(store, workspace, request, connections)[3]


def _current(store, workspace, prepared, expected_revision):
    current = prepare_analysis(store, workspace, prepared.request)
    if (current.manifest_hash != prepared.manifest_hash or current.prior_revision != prepared.prior_revision
            or _state_revision(store, workspace) != expected_revision):
        raise ValueError('source_or_configuration_changed')


def _cached(store, workspace, unit, context_hash):
    rows = store.rows('''SELECT u.result FROM ai_analysis_units u
        JOIN ai_analysis_runs r ON u.run_id=r.run_id AND u.workspace_id=r.workspace_id
        WHERE u.workspace_id=? AND u.unit_id=? AND u.context_hash=? AND u.status='validated'
        ORDER BY r.created_at DESC LIMIT 1''', [workspace, unit.unit_id, context_hash])
    if not rows:
        return None
    try:
        result = ProjectLineageResponse.model_validate_json(rows[0]['result'])
        result.assert_unit(unit)
        return result
    except ValueError:
        return None


def run_analysis(store, workspace, request, *, connections=None, authorize=None,
                 progress=None, cancelled=None, transport=None):
    """Run only under an explicit user action; failures retain the prior graph."""
    request = AnalysisRequest.model_validate(request)
    manager = connections or current_connections()
    if request.mode == 'parser':
        result = analyze(store, workspace, request.file_ids, request.force_parser,
                         progress=progress, cancelled=cancelled)
        return AnalysisReport(run_id=result['run_id'], mode='parser', status='committed', complete=True,
            counts={k: result[k] for k in ('analyzed', 'cached', 'assets', 'edges')})
    run_id = uuid.uuid4().hex
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
                     configuration=prepared.settings, summary={'preview': preview})
            registered = True
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
            _, _, prompt_hash = analysis_prompt(unit, 'project_lineage', execution)
            context_hash = _hash({'manifest': prepared.manifest_hash, 'context': plan.context_hash,
                'prompt': prompt_hash, 'settings_revision': expected_revision,
                'validator': VALIDATOR_VERSION, 'mode': request.mode})
            response = None if request.refresh_ai else _cached(store, workspace, unit, context_hash)
            record_id = None
            if response is not None:
                counts['cache_hits'] += 1
            else:
                result = invoke_analysis_unit(store, workspace, unit, 'project_lineage', execution)
                if result is None or result.outcome != 'validated' or result.result is None:
                    raise ValueError('incomplete_ai_response')
                response, record_id = result.result, result.record_id or None
                usage_known &= result.usage_known
                _usage(counts, result)
            settings = dict(config)
            from dataforge.services import source_dialect
            metadata = next(m for m, _ in local_results if m['file_id'] == unit.file_id)
            settings['dialect'] = source_dialect(metadata, config)
            context = ValidationContext(unit=unit, workspace_id=workspace,
                source_text=sources[unit.file_id].code, settings=settings, catalog=execution.catalog,
                parser_result=parser[unit.file_id])
            validated = validate_project_response(response, context)
            parser_indexes = {id(op): i for i, op in enumerate(parser[unit.file_id].operations)}
            original_indexes[unit.file_id].update({key: parser_indexes[id(op)]
                for op, _, _, key in operation_contexts(context, parser[unit.file_id])})
            cacheable = (not validated.rejected and not validated.unresolved
                         and validated.coverage.status in {'complete', 'no_operations'})
            # Rejected/unsupported model bodies are not an implicit history store.
            # Complete validated responses contain only minimal source-backed claims.
            save_unit_result(store, workspace, run_id, unit.unit_id, file_id=unit.file_id,
                content_hash=unit.content_hash, start_char=unit.start_offset, end_char=unit.end_offset,
                context_hash=context_hash, status='validated' if cacheable else 'partial', record_id=record_id,
                result=response.model_dump() if cacheable else {})
            reconciled = reconcile_candidates(parser[unit.file_id], validated, request.mode, context=context)
            candidates = [f for f in reconciled.facts if f.origin == 'ai']
            if request.additional_ai_review and candidates:
                stage = 'reviewing'
                execution.review_candidates, rejected_ids = review_payload(candidates)
                validated.unresolved.extend(ClaimDecision(candidate_id=cid,
                    reason='additional_ai_review_context_limit', status='unresolved') for cid in sorted(rejected_ids))
                if execution.review_candidates:
                    review = invoke_analysis_unit(store, workspace, unit, 'lineage_review', execution)
                    if review is None or review.outcome != 'validated' or review.result is None:
                        raise ValueError('incomplete_ai_review')
                    usage_known &= review.usage_known
                    _usage(counts, review)
                    review.result.assert_candidates({c['candidate_id'] for c in execution.review_candidates})
                    for decision in review.result.decisions:
                        if decision.decision != 'supported' or not decision.evidence:
                            rejected_ids.add(decision.candidate_id)
                            validated.unresolved.append(ClaimDecision(candidate_id=decision.candidate_id,
                                reason='additional_ai_review_insufficient', status='unresolved'))
                validated.accepted = [f for f in validated.accepted if f.candidate_id not in rejected_ids]
                reconciled = reconcile_candidates(parser[unit.file_id], validated, request.mode, context=context)
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
                    'payload': fact.model_dump(), 'record_id': record_id, 'reasons': []})
            for ordinal, fact in enumerate(reconciled.parser_only):
                claims.append({'claim_id': stable_id(unit.unit_id, 'parser', str(ordinal)),
                    'unit_id': unit.unit_id, 'kind': fact.kind,
                    'status': 'parser_only', 'payload': fact.model_dump(), 'reasons': ['ai_omission']})
            for decision in [*validated.rejected, *validated.unresolved]:
                claims.append({'claim_id': decision.candidate_id or stable_id(unit.unit_id, decision.reason),
                    'unit_id': unit.unit_id, 'kind': 'decision', 'status': decision.status,
                    'payload': {}, 'reasons': [decision.reason]})
            counts['processed'] += 1
            update(.1 + .75 * (index + 1) / max(1, len(plan.units)), 'AI extraction and evidence checks')
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
        counts['requests'] = execution.attempts
        counts['reserved_output_tokens'] = execution.reserved_output_tokens
        if not execution.attempts:
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
        status = 'cancelled' if isinstance(exc, InterruptedError) else (
            'stale' if reason == 'source_or_configuration_changed' else 'blocked' if not registered else 'failed')
        if execution:
            counts['requests'] = execution.attempts
        report = AnalysisReport(run_id=run_id, mode=request.mode, status=status, counts=dict(counts),
            usage_known=False, reasons=[reason])
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
    report = load_analysis_report(store, workspace, run_id)
    if report is None:
        raise ValueError('Analysis report not found')
    report.pop('configuration', None)
    for claim in report['claims']:
        if not include_source:
            claim.pop('payload', None)
    return report
