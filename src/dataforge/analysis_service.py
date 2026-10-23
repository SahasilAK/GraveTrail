"""One resumable extraction loop; deterministic publication from saved files."""
from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from dataclasses import asdict

from dataforge.ai_analysis_models import AnalysisReport, AnalysisRequest, FilePart
from dataforge.ai_analysis_store import (
    active_project_runs,
    load_analysis_report,
    load_file_extractions,
    load_file_parts,
    save_file_extraction,
    save_part_extraction,
    save_run,
    save_unit_result,
)
from dataforge.ai_batching import pack_request
from dataforge.ai_composition import assemble_file_extraction, merge_extraction_revision, plan_file_consolidation
from dataforge.ai_context import inventory_revision, plan_file_parts, prepare_analysis
from dataforge.ai_context_index import build_context_index, context_for_part, plan_context_completion
from dataforge.ai_pipeline_store import attempt_totals, begin_attempt, finish_attempt, recover_pipeline, save_request
from dataforge.ai_validation import validate_extraction
from dataforge.ai_wire import decode_extractions
from dataforge.connections import connection_scope, current_connections
from dataforge.llm import Adapter, ProviderError, analysis_routes, is_local
from dataforge.llm_resources import request_slot
from dataforge.model_capabilities import execution_profile
from dataforge.models import stable_id
from dataforge.services import analyze, publish_analysis_results
from dataforge.settings_service import revision


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _state_revision(store, workspace):
    merged = store.rows("SELECT record_id FROM llm_records WHERE workspace_id=? AND outcome='merged' ORDER BY record_id", [workspace])
    return _hash({'settings': revision(store, workspace), 'merged': merged})


def _protocol_hash():
    from dataforge.ai_batching import extraction_instructions
    return _hash({'protocol': 5, 'instructions': extraction_instructions()})


def _compatible_request(request):
    if request.mode == 'hybrid' or request.additional_ai_review:
        raise ValueError('Hybrid comparison and additional review are no longer supported; choose parser or ai')
    removed = ('max_files_per_request', 'max_parallel_requests', 'max_context_chars',
               'project_max_provider_attempts', 'project_max_output_tokens_total', 'project_max_seconds')
    if any(getattr(request, key) is not None for key in removed) or not request.auto_continue:
        raise ValueError('Legacy window, worker, character and batch options are no longer supported; use token limits')


def _resume_request(store, workspace, request):
    if not request.resume_run_id:
        _compatible_request(request)
        return request, {}
    rows = store.rows('SELECT status,summary FROM ai_analysis_runs WHERE workspace_id=? AND run_id=?', [workspace, request.resume_run_id])
    if not rows or rows[0]['status'] not in {'awaiting_continuation', 'interrupted', 'cancelled', 'failed'}:
        raise ValueError('Run is not available for continuation')
    summary = json.loads(rows[0]['summary'])
    if summary.get('protocol_version') != 5:
        raise ValueError('Legacy analysis checkpoint is incompatible; start a new build')
    saved = AnalysisRequest.model_validate(summary['request'])
    if request.file_ids is not None and request.file_ids != saved.file_ids:
        raise ValueError('Continuation source selection is pinned')
    if request.mode not in {'parser', saved.mode}:
        raise ValueError('Continuation analysis mode is pinned')
    for key in ('max_provider_attempts', 'max_output_tokens_total', 'max_seconds'):
        if getattr(request, key) is not None and getattr(request, key) != getattr(saved, key):
            raise ValueError('Continuation spending ceilings are pinned')
    return saved.model_copy(update={'resume_run_id': request.resume_run_id, 'retry_unknown': request.retry_unknown}), summary


def _prepare(store, workspace, request, connections=None, cancelled=None, transport=None, authorize=None,
             preparation_progress=None):
    from dataforge.ai_budget import effective_limits
    prepared = prepare_analysis(store, workspace, request, progress=preparation_progress)
    profile_id, profile = analysis_routes(store, workspace, 'project_lineage')[0]
    index = build_context_index(prepared, [])
    parts = [p for source in prepared.sources for p in plan_file_parts(source, {}, profile)]
    definitions, pinned = {}, []
    limits = effective_limits(profile)
    budget = max(0, (limits.input_tokens or limits.context_tokens or 0) // 4)
    for part in parts:
        selection = context_for_part(index, part, budget)
        pinned.append(part.model_copy(update={'context_ids': [e.entry_id for e in selection.entries],
            'context_hashes': [selection.fingerprint], 'context_references': [r for e in selection.entries for r in e.evidence]}))
        definitions[part.part_id] = selection.wire
    context = {'sources': index.sources, 'definitions': definitions}
    pending, estimates = list(pinned), []
    while pending:
        planned = pack_request(pending, profile, context)
        estimates.append(planned)
        pending = pending[len(planned.part_ids):]
    if cancelled and cancelled():
        raise InterruptedError('cancelled')
    preview = {'valid': True, 'mode': 'ai', 'source_kind': next((p.source_kind for p in parts), ''),
        'files': len(prepared.sources), 'parts': len(parts), 'units': len(parts), 'blocked': [],
        'routes': {'project_lineage': [{'provider': profile.provider, 'model': profile.model}]},
        'estimated_requests': len(estimates), 'max_provider_attempts': len(estimates),
        'estimated_input_tokens': sum(p.budget.input_count for p in estimates),
        'estimated_output_tokens': sum(p.reserved_output for p in estimates), 'limits': asdict(limits),
        'estimate_method': estimates[0].budget.count_method if estimates else '',
        'disclosure': [{'file_id': s.file_id, 'path': s.path, 'content_hash': s.content_hash,
                        'characters': len(s.code), 'source_kind': s.source_kind} for s in prepared.sources]}
    return prepared, pinned, (profile_id, profile), context, preview


def preview_analysis(store, workspace, request, *, connections=None, progress=None):
    request, _ = _resume_request(store, workspace, AnalysisRequest.model_validate(request))
    if request.mode == 'parser':
        return {'valid': True, 'mode': 'parser', 'files': len(store.files(workspace)), 'parts': 0,
                'units': 0, 'blocked': [], 'routes': {}, 'max_provider_attempts': 0}
    try:
        return _prepare(store, workspace, request, connections, preparation_progress=progress)[4]
    except ValueError as exc:
        return {'valid': False, 'mode': 'ai', 'files': 0, 'parts': 0, 'units': 0,
                'blocked': [{'reason': str(exc)}], 'routes': {}, 'disclosure': [], 'max_provider_attempts': 0}


def _current(store, workspace, prepared, expected_revision, *, full=False):
    prior = store.rows("SELECT run_id FROM analysis_runs WHERE workspace_id=? AND status='completed' ORDER BY created_at DESC LIMIT 1", [workspace])
    if (inventory_revision(store, workspace) != prepared.inventory_revision or
            (prior[0]['run_id'] if prior else '') != prepared.prior_revision or
            _state_revision(store, workspace) != expected_revision):
        raise ValueError('source_or_configuration_changed')
    if full and prepare_analysis(store, workspace, prepared.request).manifest_hash != prepared.manifest_hash:
        raise ValueError('source_or_configuration_changed')


def run_analysis(store, workspace, request, *, connections=None, authorize=None,
                 progress=None, cancelled=None, transport=None):
    request = AnalysisRequest.model_validate(request)
    manager = connections or current_connections()
    run_id = request.resume_run_id or uuid.uuid4().hex
    registered, stage, summary = False, 'planning', {}
    counts, usage_known = Counter(), True
    def update(name):
        if progress:
            progress(min(.85, .1 + counts['processed'] / max(1, counts['parts']) * .7), name)
    try:
        request, summary = _resume_request(store, workspace, request)
        if request.mode == 'parser':
            result = analyze(store, workspace, request.file_ids, request.force_parser, progress=progress, cancelled=cancelled)
            return AnalysisReport(run_id=result['run_id'], mode='parser', status='committed', complete=True,
                counts={k: result[k] for k in ('analyzed', 'cached', 'assets', 'edges')})
        with store.analysis_lock:
            if active_project_runs(store, workspace):
                raise ValueError('analysis_already_active')
            prepared, parts, route, context, preview = _prepare(store, workspace, request, manager, cancelled)
            pid, profile = route
            expected = _state_revision(store, workspace)
            pin = {'manifest': prepared.manifest_hash, 'revision': expected, 'prior': prepared.prior_revision,
                   'protocol': _protocol_hash(), 'profile': _hash(execution_profile(profile))}
            if request.resume_run_id and summary.get('pin') != pin:
                raise ValueError('source_or_configuration_changed')
            if request.resume_run_id:
                unknown = recover_pipeline(store, workspace, run_id)['unknown']
                if unknown and not request.retry_unknown:
                    return AnalysisReport(run_id=run_id, mode='ai', status='awaiting_continuation',
                        reasons=['unknown_inflight_request_requires_explicit_retry'])
                for attempt in unknown:
                    store.execute("UPDATE ai_analysis_attempts SET status='retry_authorized' WHERE attempt_id=?", [attempt['attempt_id']])
                parts = [FilePart.model_validate(p) for p in summary['parts']]
            counts.update(summary.get('counts', {}))
            counts['files'], counts['parts'] = len(prepared.sources), len(parts)
            summary.update(protocol_version=5, request=request.model_dump(), pin=pin, parts=[p.model_dump() for p in parts])
            save_run(store, workspace, run_id, mode='ai', status='extracting', manifest=prepared.manifest,
                     configuration=prepared.settings, summary=summary)
            registered = True

        def checkpoint():
            summary.update(counts=dict(counts), stage=stage, usage_known=usage_known)
            save_run(store, workspace, run_id, mode='ai', status=stage, summary=summary)

        def check():
            if cancelled and cancelled():
                raise InterruptedError('cancelled')
            _current(store, workspace, prepared, expected)
            if not is_local(profile.base_url) and not (store.setting(workspace, 'external_llm', False)
                                                       and store.setting(workspace, 'allow_full_source', False)):
                raise ValueError('complete_source_permission_required')
            if authorize:
                authorize(profile)

        def execute(work, work_context):
            nonlocal usage_known
            saved = {p.part_id for p, _ in load_file_parts(store, workspace, run_id)}
            pending = [p for p in work if p.part_id not in saved]
            errors = summary.setdefault('item_failures', {})
            while pending:
                check()
                truncated = False
                planned = pack_request(pending, profile, work_context)
                scheduled = [p for p in pending if p.part_id in planned.part_ids]
                batch_id = stable_id(run_id, planned.serialized_payload)
                save_request(store, workspace, run_id, batch_id, list(planned.part_ids),
                    details={'work_kind': scheduled[0].work_kind, 'budget': asdict(planned.budget)})
                ticket = None
                def before_attempt(_profile):
                    nonlocal ticket
                    check()
                    from dataforge.ai_budget import request_budget
                    if not request_budget(profile, planned.serialized_payload, planned.reserved_output).fits:
                        raise ValueError('dispatch_budget_changed')
                    attempts, reserved = attempt_totals(store, workspace, run_id)
                    if request.max_output_tokens_total is not None and reserved + planned.reserved_output > request.max_output_tokens_total:
                        raise TimeoutError('run_output_ceiling_reached')
                    if request.max_provider_attempts is not None and attempts >= request.max_provider_attempts:
                        raise TimeoutError('run_attempt_ceiling_reached')
                    ticket = begin_attempt(store, workspace, run_id, batch_id, planned.reserved_output)
                    update('Waiting for AI ' + scheduled[0].work_kind + ' response')
                    return profile.timeout
                def observed(status, limits):
                    if status >= 300 and ticket:
                        finish_attempt(store, workspace, run_id, ticket, 'known_failure')
                bound = manager.for_profile(pid, profile) if hasattr(manager, 'for_profile') else manager
                try:
                    with connection_scope(bound), request_slot(store.home, workspace, 1), Adapter(profile,
                            transport=transport, cancelled=cancelled, before_attempt=before_attempt, check=check,
                            response_observer=observed, retry_unknown_transports=False) as adapter:
                        raw, usage = adapter.complete(planned.system, planned.user)
                        metadata = adapter.completion_metadata
                    if ticket:
                        finish_attempt(store, workspace, run_id, ticket, 'received')
                    usage_known &= metadata.get('usage_known', False)
                    for key, aliases in {'input_tokens': ('input_tokens', 'prompt_tokens', 'promptTokenCount'),
                                         'output_tokens': ('output_tokens', 'completion_tokens', 'candidatesTokenCount')}.items():
                        counts[key] += next((usage[a] for a in aliases if type(usage.get(a)) is int), 0)
                    if metadata.get('truncated'):
                        truncated = True
                        raise ValueError('truncated_extraction_response')
                    valid, invalid = decode_extractions(raw, scheduled)
                except ProviderError as exc:
                    if exc.unknown and ticket:
                        finish_attempt(store, workspace, run_id, ticket, 'unknown')
                        raise TimeoutError('unknown_inflight_request_requires_explicit_retry') from None
                    raise TimeoutError(str(exc)) from None
                except ValueError:
                    valid, invalid = {}, {p.part_id: 'invalid_extraction_response' for p in scheduled}
                for part in scheduled:
                    item = valid.get(part.part_id)
                    if item is not None:
                        try:
                            item = validate_extraction(item, part, context['sources'])
                            save_part_extraction(store, workspace, run_id, part, item)
                            counts['processed'] += 1
                            saved.add(part.part_id)
                        except ValueError:
                            invalid[part.part_id] = 'invalid_source_or_internal_reference'
                    if part.part_id not in saved:
                        errors[part.part_id] = errors.get(part.part_id, 0) + 1
                store.execute("UPDATE ai_analysis_requests SET status='processed' WHERE batch_id=?", [batch_id])
                counts['requests'], counts['reserved_output_tokens'] = attempt_totals(store, workspace, run_id)
                checkpoint()
                failed = [p for p in scheduled if p.part_id not in saved]
                if truncated:
                    for parent in list(failed):
                        if parent.work_kind != 'extraction' or parent.end_offset - parent.start_offset < 2:
                            continue
                        middle = (parent.start_offset + parent.end_offset) // 2
                        children = [parent.model_copy(update={
                            'part_id': stable_id('extraction5', parent.file_id, parent.content_hash, str(a), str(b)),
                            'start_offset': a, 'end_offset': b}) for a, b in
                            ((parent.start_offset, middle), (middle, parent.end_offset))]
                        save_unit_result(store, workspace, run_id, parent.part_id, file_id=parent.file_id,
                            content_hash=parent.content_hash, status='superseded', result={'contract': 'superseded5'})
                        parts.remove(parent)
                        parts.extend(children)
                        pending.remove(parent)
                        pending.extend(children)
                        for child in children:
                            work_context['definitions'][child.part_id] = work_context['definitions'].get(parent.part_id, [])
                        failed.remove(parent)
                    summary['parts'] = [p.model_dump() for p in parts]
                    counts['parts'] = len(parts)
                    checkpoint()
                if any(errors[p.part_id] >= 2 for p in failed):
                    raise ValueError('missing_or_invalid_required_extraction')
                pending = [p for p in pending if p.part_id not in saved]

        stage = 'extracting'
        update('Extracting file contents')
        execute(parts, context)
        initial = {p.part_id: (p, r) for p, r in load_file_parts(store, workspace, run_id) if p.work_kind == 'extraction'}
        if 'completion_work' not in summary:
            frozen = build_context_index(prepared, [r for _, r in initial.values()])
            works = plan_context_completion(list(initial.values()), frozen)
            summary['completion_work'] = [{'part': w.part.model_dump(), 'original': w.original_part_id,
                'definitions': w.context.wire, 'catalog_revision': w.catalog_revision} for w in works]
            checkpoint()
        works = summary['completion_work']
        completion_context = {**context, 'definitions': {w['part']['part_id']: w['definitions'] for w in works},
            'work_inputs': {w['part']['part_id']: initial[w['original']][1].model_dump() for w in works}}
        bounded = []
        for work in works:
            part = FilePart.model_validate(work['part'])
            try:
                pack_request([part], profile, completion_context)
                bounded.append(part)
            except ValueError:
                initial[work['original']][1].unresolved.append('completion_context_exceeds_budget')
        update('Completing affected source context')
        execute(bounded, completion_context)
        saved = {p.part_id: r for p, r in load_file_parts(store, workspace, run_id)}
        for work in works:
            if work['part']['part_id'] in saved:
                original, item = initial[work['original']]
                initial[original.part_id] = (original, merge_extraction_revision(item, saved[work['part']['part_id']]))
        stage = 'consolidating'
        checkpoint()
        for source in prepared.sources:
            if source.source_kind not in {'sql', 'sas', 'dbt'}:
                continue
            file_parts = [(p, r) for p, r in initial.values() if p.file_id == source.file_id]
            groups = plan_file_consolidation(file_parts, profile)
            execute([g.part for g in groups if not g.overflow],
                {**context, 'work_inputs': {g.part.part_id: g.inputs for g in groups if not g.overflow}})
            consolidated = [r for p, r in load_file_parts(store, workspace, run_id, source.file_id) if p.work_kind == 'consolidation']
            final = assemble_file_extraction(source, file_parts, consolidated,
                provenance={'profile': execution_profile(profile), 'prompt': pin['protocol'], 'schema': 5})
            if any(g.overflow for g in groups):
                final.unresolved.append('consolidation_context_exceeds_budget')
                final.semantic_coverage = 'partial'
            save_file_extraction(store, workspace, run_id, final)
        stage = 'linking'
        checkpoint()
        update('Linking saved file results')
        from dataforge.ai_linking import link_file_extractions, to_publication_results
        files = load_file_extractions(store, workspace, run_id)
        if len(files) != sum(s.source_kind in {'sql', 'sas', 'dbt'} for s in prepared.sources):
            raise ValueError('missing_required_file_extraction')
        linked = link_file_extractions(files, prepared.settings)
        inventory = {s.file_id: {**store.file(s.file_id), 'source_text': s.code} for s in prepared.sources}
        results = to_publication_results(linked, inventory)
        counts['accepted'] = sum(len(f.operations) for f in files)
        counts['unresolved'] = len(linked.unresolved)
        counts['coverage_gaps'] = sum(f.semantic_coverage != 'model_reported_complete' for f in files) + len(linked.unresolved)
        with store.analysis_lock, store.transaction():
            check()
            _current(store, workspace, prepared, expected, full=True)
            published = publish_analysis_results(store, workspace, results, prepared.settings,
                {'analyzed': len(files), 'cached': 0}, cancelled=cancelled)
            counts.update({k: published[k] for k in ('analyzed', 'cached', 'assets', 'edges')})
            report = AnalysisReport(run_id=run_id, mode='ai', status='committed', complete=not counts['coverage_gaps'],
                counts=dict(counts), usage_known=usage_known,
                reasons=['semantic_coverage_not_proven'] if counts['coverage_gaps'] else [])
            save_run(store, workspace, run_id, mode='ai', status='committed', analysis_run_id=published['run_id'],
                accepted_results=results, summary={**summary, **report.model_dump()})
        if progress:
            progress(1., 'Publication complete')
        return report
    except (ValueError, OSError, TimeoutError, InterruptedError) as exc:
        reason = 'cancelled' if isinstance(exc, InterruptedError) else manager.redact(str(exc))[:500]
        status = ('stale' if reason == 'source_or_configuration_changed' else 'cancelled' if isinstance(exc, InterruptedError)
                  else 'awaiting_continuation' if isinstance(exc, TimeoutError) and registered else 'failed' if registered else 'blocked')
        if registered:
            counts['requests'], counts['reserved_output_tokens'] = attempt_totals(store, workspace, run_id)
        report = AnalysisReport(run_id=run_id, mode=request.mode, status=status, counts=dict(counts), reasons=[reason])
        if registered or status == 'stale':
            save_run(store, workspace, run_id, mode='ai', status=status,
                summary={**summary, **report.model_dump(), 'stage': stage})
        return report
    except Exception:
        if registered:
            save_run(store, workspace, run_id, mode='ai', status='failed', summary={'reasons': ['internal_error'], 'stage': stage})
        raise


def analysis_report(store, workspace, run_id=None, *, include_source=False):
    report = load_analysis_report(store, workspace, run_id, include_source=include_source)
    if report is None:
        raise ValueError('Analysis report not found')
    report.pop('configuration', None)
    return report
