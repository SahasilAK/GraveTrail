"""One resumable extraction loop; deterministic publication from saved files."""
from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from dataclasses import asdict
from time import monotonic

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
from dataforge.ai_composition import (
    assemble_file_extraction,
    merge_extraction_revision,
    plan_file_consolidation,
)
from dataforge.ai_context import inventory_revision, plan_file_parts, prepare_analysis
from dataforge.ai_context_index import build_context_index, context_for_part, plan_context_completion
from dataforge.ai_pipeline_store import (
    attempt_totals,
    batch_attempts,
    begin_attempt,
    finish_attempt,
    recover_pipeline,
    save_request,
)
from dataforge.ai_validation import validate_extraction
from dataforge.ai_wire import decode_extractions
from dataforge.connections import connection_scope, current_connections
from dataforge.llm import Adapter, ProviderError, analysis_routes, is_local
from dataforge.llm_resources import request_slot
from dataforge.model_capabilities import execution_profile
from dataforge.models import stable_id
from dataforge.services import (
    analyze,
    publish_analysis_results,
    restore_manual_ai_results,
    retained_publication_results,
)
from dataforge.settings_service import revision


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def recovery_message(summary):
    """Explain observed connection state without speculating about upstreams."""
    detail = summary.get('last_failure', {})
    category = detail.get('failure_category')
    if summary.get('status') == 'committed' or summary.get('reasons') == ['semantic_coverage_not_proven']:
        return 'Published AI lineage remains inferred; semantic completeness is not proven.'
    if any(r.startswith('run_') and r.endswith('_reached') for r in summary.get('reasons', [])):
        return 'The run limit was reached. Saved progress is retained; continuation does not reset the limit.'
    message = {'transport_unknown': 'The gateway connection ended before a complete response arrived; processing or charges may have occurred.',
        'pre_send': 'The connection could not be established; the inference request was not sent.',
        'authentication': 'The provider rejected authentication. Check the configured credentials.',
        'http_failure': 'The gateway returned an HTTP error.',
        'cancelled': 'AI analysis was cancelled. Saved progress is retained.',
        'invalid_response': 'The provider returned an invalid response.',
        'process_interrupted': 'The app stopped before it checkpointed a complete response; the outcome is unknown.'}.get(category)
    if category == 'transport_unknown' and detail.get('transport_error') == 'ReadTimeout':
        message = 'The app timed out waiting for response data; processing or charges may have occurred.'
    if not message:
        return 'AI analysis paused with saved progress. Review the report before continuing.'
    if detail.get('retry_scheduled'):
        message += f" Retrying batch {detail.get('batch_number', 1)}, attempt {detail.get('cycle_attempt', detail.get('attempt_number', 1)) + 1} of {detail.get('attempt_limit', 1)}."
    elif detail.get('allowance_exhausted'):
        message += ' The automatic retry allowance is exhausted. Manual acknowledgement is required to retry.'
    return message


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
    _compatible_request(request)
    if not request.resume_run_id:
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
    manager = connections or current_connections()
    bound = manager.for_profile(profile_id, profile) if hasattr(manager, 'for_profile') else manager
    if profile.key_env and not bound.resolve(profile.key_env):
        raise ValueError('Configured provider credential is unavailable')
    index = build_context_index(prepared, [])
    definitions, pinned = {}, []
    limits = effective_limits(profile)
    budget = max(0, (limits.input_tokens or limits.context_tokens or 0) // 4)
    domain_settings = {k: prepared.settings[k] for k in ('dialect', 'dialect_by_extension',
        'dialect_by_folder', 'macros', 'library_mappings') if k in prepared.settings}
    parts = [p for source in prepared.sources for p in plan_file_parts(source,
        {'index': index, 'context_budget': budget, 'settings': domain_settings}, profile)]
    for part in parts:
        selection = context_for_part(index, part, budget)
        pinned.append(part.model_copy(update={'context_ids': [e.entry_id for e in selection.entries],
            'context_hashes': [selection.fingerprint], 'context_references': [r for e in selection.entries for r in e.evidence]}))
        definitions[part.part_id] = selection.wire
    context = {'sources': index.sources, 'definitions': definitions, 'settings': domain_settings}
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
    started = monotonic()
    prior_seconds = 0.
    def update(name):
        if progress:
            progress(min(.85, .1 + counts['processed'] / max(1, counts['parts']) * .7), name)
    try:
        request, summary = _resume_request(store, workspace, request)
        prior_seconds = summary.get('active_seconds', 0.)
        counts.update(summary.get('counts', {}))
        usage_known = summary.get('usage_known', True)
        if request.mode == 'parser':
            result = analyze(store, workspace, request.file_ids, request.force_parser, progress=progress, cancelled=cancelled)
            return AnalysisReport(run_id=result['run_id'], mode='parser', status='committed', complete=True,
                counts={k: result[k] for k in ('analyzed', 'cached', 'assets', 'edges')})
        with store.analysis_lock:
            if active_project_runs(store, workspace):
                raise ValueError('analysis_already_active')
            try:
                prepared, parts, route, context, preview = _prepare(store, workspace, request, manager, cancelled)
            except ValueError:
                if request.resume_run_id:
                    raise ValueError('source_or_configuration_changed') from None
                raise
            pid, profile = route
            expected = _state_revision(store, workspace)
            pin = {'manifest': prepared.manifest_hash, 'revision': expected, 'prior': prepared.prior_revision,
                   'protocol': _protocol_hash(), 'profile': _hash(execution_profile(profile))}
            if request.resume_run_id and summary.get('pin') != pin:
                raise ValueError('source_or_configuration_changed')
            if request.resume_run_id:
                historical = store.rows('SELECT status,details FROM ai_analysis_attempts WHERE workspace_id=? AND run_id=?', [workspace, run_id])
                if any(a['status'] in {'unknown', 'dispatched'} or json.loads(a['details']).get('usage_known') is False
                       or json.loads(a['details']).get('uncheckpointed_response')
                       for a in historical):
                    usage_known = False
                unknown = recover_pipeline(store, workspace, run_id)['unknown']
                if unknown:
                    usage_known = False
                for attempt in unknown:
                    if attempt['status'] == 'dispatched':
                        finish_attempt(store, workspace, run_id, attempt['attempt_id'], 'unknown',
                            details={'failure_category': 'process_interrupted', 'outcome': 'unknown',
                                     'elapsed_seconds': None, 'http_status': None, 'retry_scheduled': False,
                                     'allowance_exhausted': False})
                    elif attempt['status'] == 'received':
                        details = {**json.loads(attempt['details']), 'uncheckpointed_response': True, 'usage_known': False}
                        store.execute('UPDATE ai_analysis_attempts SET details=? WHERE attempt_id=?', [json.dumps(details), attempt['attempt_id']])
                if unknown and not request.retry_unknown and not profile.unknown_retries:
                    counts['requests'], counts['reserved_output_tokens'] = attempt_totals(store, workspace, run_id)
                    save_run(store, workspace, run_id, mode='ai', status='awaiting_continuation',
                             summary={**summary, 'counts': dict(counts), 'usage_known': False})
                    return AnalysisReport(run_id=run_id, mode='ai', status='awaiting_continuation',
                        counts=dict(counts), usage_known=False, reasons=['unknown_inflight_request_requires_explicit_retry'])
                if request.retry_unknown:
                    for row in store.rows('SELECT batch_id,details FROM ai_analysis_requests WHERE run_id=? AND workspace_id=? AND status<>?',
                                          [run_id, workspace, 'processed']):
                        details = {**json.loads(row['details']), 'manual_retry_baseline': len(batch_attempts(store, workspace, run_id, row['batch_id']))}
                        store.execute('UPDATE ai_analysis_requests SET details=? WHERE batch_id=?', [json.dumps(details), row['batch_id']])
                    for attempt in unknown:
                        details = {**json.loads(attempt['details']), 'retry_authorized': True}
                        store.execute('UPDATE ai_analysis_attempts SET details=? WHERE attempt_id=?', [json.dumps(details), attempt['attempt_id']])
                elif summary.get('reasons') == ['missing_or_invalid_required_extraction']:
                    # Explicit continuation after known received-but-invalid items
                    # may start new semantic work. Automatic loops never renew it.
                    for row in store.rows("SELECT batch_id,details FROM ai_analysis_requests WHERE workspace_id=? AND run_id=? AND status='processed'", [workspace, run_id]):
                        history = batch_attempts(store, workspace, run_id, row['batch_id'])
                        if history and history[-1]['status'] == 'received':
                            details = {**json.loads(row['details']), 'manual_retry_baseline': len(history)}
                            store.execute('UPDATE ai_analysis_requests SET details=? WHERE batch_id=?', [json.dumps(details), row['batch_id']])
                parts = [FilePart.model_validate(p) for p in summary['parts']]
            counts['files'], counts['parts'] = len(prepared.sources), len(parts)
            summary.update(protocol_version=5, request=request.model_dump(), pin=pin, parts=[p.model_dump() for p in parts],
                           retry_policy={'unknown_retries': profile.unknown_retries, 'shared_retries': profile.retries})
            save_run(store, workspace, run_id, mode='ai', status='extracting', manifest=prepared.manifest,
                     configuration=prepared.settings, summary=summary)
            registered = True

        def checkpoint():
            summary.update(counts=dict(counts), stage=stage, usage_known=usage_known,
                           active_seconds=prior_seconds + monotonic() - started)
            save_run(store, workspace, run_id, mode='ai', status=stage, summary=summary)

        def check():
            if cancelled and cancelled():
                raise InterruptedError('cancelled')
            if request.max_seconds is not None and prior_seconds + monotonic() - started >= request.max_seconds:
                raise TimeoutError('run_time_ceiling_reached')
            _current(store, workspace, prepared, expected)
            if _protocol_hash() != pin['protocol']:
                raise ValueError('source_or_configuration_changed')
            if not is_local(profile.base_url) and not (store.setting(workspace, 'external_llm', False)
                                                       and store.setting(workspace, 'allow_full_source', False)):
                raise ValueError('complete_source_permission_required')
            if authorize:
                authorize(profile)
            bound = manager.for_profile(pid, profile) if hasattr(manager, 'for_profile') else manager
            if profile.key_env and not bound.resolve(profile.key_env):
                raise ValueError('Configured provider credential is unavailable')

        def execute(work, work_context):
            nonlocal usage_known
            if not work:
                return
            saved = {r['unit_id'] for r in store.rows("SELECT unit_id FROM ai_analysis_units WHERE workspace_id=? AND run_id=? AND status='completed'",
                                                     [workspace, run_id])}
            pending = [p for p in work if p.part_id not in saved]
            errors = summary.setdefault('item_failures', {})
            while pending:
                check()
                truncated = False
                planned = pack_request(pending, profile, work_context)
                scheduled = [p for p in pending if p.part_id in planned.part_ids]
                batch_id = stable_id(run_id, planned.serialized_payload)
                save_request(store, workspace, run_id, batch_id, list(planned.part_ids),
                    details={'work_kind': scheduled[0].work_kind, 'budget': asdict(planned.budget),
                             'batch_number': len(store.rows('SELECT batch_id FROM ai_analysis_requests WHERE workspace_id=? AND run_id=?', [workspace, run_id])) + 1})
                ticket = None
                physical_started = monotonic()
                def before_attempt(_profile):
                    nonlocal ticket, physical_started
                    update('Waiting for AI ' + scheduled[0].work_kind + ' response')
                    check()
                    from dataforge.ai_budget import request_budget
                    if not request_budget(profile, planned.serialized_payload, planned.reserved_output).fits:
                        raise ValueError('dispatch_budget_changed')
                    attempts, reserved = attempt_totals(store, workspace, run_id)
                    def ceiling(reason):
                        if summary.get('last_failure'):
                            summary['last_failure'].update(retry_scheduled=False, allowance_exhausted=True)
                        raise TimeoutError(reason)
                    if request.max_output_tokens_total is not None and reserved + planned.reserved_output > request.max_output_tokens_total:
                        ceiling('run_output_ceiling_reached')
                    if request.max_provider_attempts is not None and attempts >= request.max_provider_attempts:
                        ceiling('run_attempt_ceiling_reached')
                    history = batch_attempts(store, workspace, run_id, batch_id)
                    request_details = json.loads(store.rows('SELECT details FROM ai_analysis_requests WHERE batch_id=?', [batch_id])[0]['details'])
                    baseline = request_details.get('manual_retry_baseline', 0)
                    cycle = history[baseline:]
                    if len(cycle) >= profile.retries + 1 or sum(a['status'] == 'unknown' or
                        json.loads(a['details']).get('uncheckpointed_response', False) for a in cycle) > profile.unknown_retries:
                        if summary.get('last_failure'):
                            summary['last_failure'].update(retry_scheduled=False, allowance_exhausted=True)
                        raise TimeoutError('batch_retry_allowance_exhausted')
                    ticket = begin_attempt(store, workspace, run_id, batch_id, planned.reserved_output,
                        details={'attempt_number': len(history) + 1, 'cycle_attempt': len(cycle) + 1,
                                 'attempt_limit': profile.retries + 1, 'batch_number': request_details.get('batch_number', 1), 'timeouts': {
                            'connect': profile.connect_timeout, 'read': None if profile.wait_until_stopped else (profile.read_timeout or profile.timeout),
                            'write': profile.timeout, 'pool': profile.connect_timeout}})
                    physical_started = monotonic()
                def observed_failure(detail):
                    nonlocal usage_known
                    if ticket:
                        attempt = store.rows('SELECT status,details FROM ai_analysis_attempts WHERE attempt_id=?', [ticket])[0]
                        if attempt['status'] != 'dispatched':
                            return
                        detail.update({k: v for k, v in json.loads(attempt['details']).items() if k != 'timeouts'})
                        detail.setdefault('timeouts', json.loads(attempt['details'])['timeouts'])
                        detail.setdefault('elapsed_seconds', max(0., monotonic() - physical_started))
                        detail.setdefault('http_status', None)
                        request_details = json.loads(store.rows('SELECT details FROM ai_analysis_requests WHERE batch_id=?', [batch_id])[0]['details'])
                        baseline = request_details.get('manual_retry_baseline', 0)
                        history = batch_attempts(store, workspace, run_id, batch_id)[baseline:]
                        exhausted = len(history) >= profile.retries + 1 or (
                            sum(a['status'] == 'unknown' or json.loads(a['details']).get('uncheckpointed_response', False)
                                for a in history) + int(detail['outcome'] == 'unknown') > profile.unknown_retries)
                        if exhausted:
                            detail.update(retry_scheduled=False, allowance_exhausted=True)
                        detail['usage_known'] = detail['failure_category'] in {
                            'pre_send', 'authentication', 'provider_credits_exhausted', 'provider_daily_quota_exhausted'}
                        finish_attempt(store, workspace, run_id, ticket,
                            'unknown' if detail['outcome'] == 'unknown' else 'known_failure', details=detail)
                        usage_known &= detail['usage_known']
                        summary['last_failure'] = detail
                        if detail['retry_scheduled']:
                            update(recovery_message({'last_failure': detail}))
                        checkpoint()
                bound = manager.for_profile(pid, profile) if hasattr(manager, 'for_profile') else manager
                try:
                    with connection_scope(bound), request_slot(store.home, workspace, 1), Adapter(profile,
                            transport=transport, cancelled=cancelled, before_attempt=before_attempt, check=check,
                            attempt_observer=observed_failure,
                            retry_unknown_transports=bool(profile.unknown_retries)) as adapter:
                        raw, usage = adapter.complete(planned.system, planned.user)
                        metadata = adapter.completion_metadata
                    if ticket:
                        finish_attempt(store, workspace, run_id, ticket, 'received',
                            details={**metadata, 'usage': usage})
                    usage_known &= metadata.get('usage_known', False)
                    for key, aliases in {'input_tokens': ('input_tokens', 'prompt_tokens', 'promptTokenCount'),
                                         'output_tokens': ('output_tokens', 'completion_tokens', 'candidatesTokenCount')}.items():
                        counts[key] += next((usage[a] for a in aliases if type(usage.get(a)) is int), 0)
                    try:
                        if metadata.get('truncated'):
                            truncated = True
                            raise ValueError('truncated_extraction_response')
                        valid, invalid = decode_extractions(raw, scheduled)
                    except ValueError:
                        valid, invalid = {}, {p.part_id: 'invalid_extraction_response' for p in scheduled}
                except ProviderError as exc:
                    if ticket and store.rows('SELECT status FROM ai_analysis_attempts WHERE attempt_id=?', [ticket])[0]['status'] == 'dispatched':
                        observed_failure({'failure_category': 'invalid_response', 'outcome': 'known',
                                          'retry_scheduled': False, 'allowance_exhausted': False})
                    if exc.unknown:
                        raise TimeoutError('unknown_inflight_request_requires_explicit_retry') from None
                    if cancelled and cancelled():
                        raise InterruptedError('cancelled') from None
                    raise TimeoutError(str(exc)) from None
                for part in scheduled:
                    item = valid.get(part.part_id)
                    if item is not None:
                        try:
                            item = validate_extraction(item, part, context['sources'])
                            if part.work_kind != 'extraction':
                                from dataforge.ai_analysis_models import PartExtraction
                                supplied = work_context['work_inputs'][part.part_id]
                                original = (PartExtraction.model_validate(supplied) if part.work_kind == 'context_completion' else
                                    PartExtraction(part_id=part.part_id, operations=supplied['operations']))
                                merge_extraction_revision(original, item)
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
            groups = plan_file_consolidation(file_parts, profile, context=context)
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
        # Capture this run's publication uncertainty before adding retained files.
        incomplete_files = {f.file_id for f in files if f.semantic_coverage != 'model_reported_complete'}
        incomplete_files.update(m['file_id'] for m, p in results
                                if p.metadata.get('semantic_coverage') != 'model_reported_complete')
        unresolved_resources = set(linked.unresolved) | {a.identity for _, p in results
                                                       for a in p.assets if a.kind == 'unresolved'}
        if request.file_ids is not None:
            results.extend(retained_publication_results(store, workspace, inventory, prepared.settings, prepared.prior_revision))
        restore_manual_ai_results(store, workspace, results, prepared.settings)
        from dataforge.dbt.service import prepare_ai_dbt_inventory
        dbt_projects = prepare_ai_dbt_inventory(prepared, results)
        if request.file_ids is not None:
            from dataforge.dbt.persistence import load_committed_dbt_results
            selected_projects = {p.snapshot.project_id for p in dbt_projects}
            dbt_projects.extend(p for p in load_committed_dbt_results(store, workspace) if p.snapshot.project_id not in selected_projects)
        counts['accepted'] = sum(len(f.operations) for f in files)
        counts['unresolved'] = len(unresolved_resources) + sum(len(f.unresolved) for f in files)
        counts['incomplete_files'] = len(incomplete_files)
        counts['coverage_gaps'] = counts['incomplete_files'] + len(unresolved_resources)
        with store.analysis_lock, store.transaction():
            check()
            _current(store, workspace, prepared, expected, full=True)
            published = publish_analysis_results(store, workspace, results, prepared.settings,
                {'analyzed': len(files), 'cached': 0, 'dbt_projects': dbt_projects}, cancelled=cancelled)
            counts.update({k: published[k] for k in ('analyzed', 'cached', 'assets', 'edges')})
            report = AnalysisReport(run_id=run_id, mode='ai', status='committed', complete=False,
                counts=dict(counts), usage_known=usage_known,
                reasons=['semantic_coverage_not_proven'])
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
            if summary.get('last_failure'):
                summary['last_failure']['retry_scheduled'] = False
        report = AnalysisReport(run_id=run_id, mode=request.mode, status=status, counts=dict(counts), reasons=[reason], usage_known=usage_known)
        if registered or status == 'stale':
            summary['active_seconds'] = prior_seconds + monotonic() - started
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
