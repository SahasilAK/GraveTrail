"""One resumable extraction loop; deterministic publication from saved files."""
from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from dataclasses import asdict
from time import monotonic, time

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
from dataforge.ai_batching import RECOVERY_FEEDBACK_RESERVE, pack_request
from dataforge.ai_composition import (
    ConsolidationWork,
    assemble_file_extraction,
    merge_extraction_revision,
    plan_file_consolidation,
)
from dataforge.ai_context import inventory_revision, plan_file_parts, prepare_analysis
from dataforge.ai_context_index import (
    build_context_index,
    context_for_part,
    plan_context_completion,
    restore_part_context,
)
from dataforge.ai_extraction_recovery import (
    recovery_wait,
    response_metadata,
    split_truncated_part,
    validation_failure,
)
from dataforge.ai_inspection import capture_payload, load_replayable_response
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
from dataforge.llm import (
    Adapter,
    ProviderError,
    analysis_routes,
    decode_provider_response,
    decode_wire_response,
    is_local,
)
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
    if summary.get('status') == 'committed' and (summary.get('unresolved_work') or 'required_work_unresolved' in summary.get('reasons', [])):
        return 'Available validated lineage was published with incomplete coverage. Retry unresolved work to continue; saved successes are reused.'
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
    if request.budget_policy == 'legacy' and not request.resume_run_id:
        raise ValueError('legacy_budget_policy_only_for_saved_runs')
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
    if not rows or rows[0]['status'] not in {'awaiting_continuation', 'interrupted', 'cancelled', 'failed', 'committed'}:
        raise ValueError('Run is not available for continuation')
    summary = json.loads(rows[0]['summary'])
    if rows[0]['status'] == 'committed':
        if not summary.get('unresolved_work'):
            raise ValueError('Run is not available for continuation')
        summary['_retry_partial_publication'] = True
    if summary.get('protocol_version') != 5:
        raise ValueError('Legacy analysis checkpoint is incompatible; start a new build')
    saved_values = dict(summary['request'])
    saved_values.setdefault('budget_policy', 'legacy')
    saved = AnalysisRequest.model_validate(saved_values)
    if request.file_ids is not None and request.file_ids != saved.file_ids:
        raise ValueError('Continuation source selection is pinned')
    if request.mode not in {'parser', saved.mode}:
        raise ValueError('Continuation analysis mode is pinned')
    for key in ('max_provider_attempts', 'max_output_tokens_total', 'max_seconds'):
        if getattr(request, key) is not None and getattr(request, key) != getattr(saved, key):
            raise ValueError('Continuation spending ceilings are pinned')
    for key in ('output_share', 'input_token_limit', 'output_token_limit', 'budget_policy'):
        if key in request.model_fields_set and getattr(request, key) != getattr(saved, key):
            raise ValueError('Continuation token allocation is pinned')
    return saved.model_copy(update={'resume_run_id': request.resume_run_id, 'retry_unknown': request.retry_unknown}), summary


def _prepare(store, workspace, request, connections=None, cancelled=None, transport=None, authorize=None,
             preparation_progress=None):
    from dataforge.ai_budget import allocate_analysis_profile, effective_limits
    prepared = prepare_analysis(store, workspace, request, progress=preparation_progress)
    profile_id, profile = analysis_routes(store, workspace, 'project_lineage')[0]
    credential_profile = profile
    profile, allocation = allocate_analysis_profile(profile, request)
    manager = connections or current_connections()
    bound = manager.for_profile(profile_id, credential_profile) if hasattr(manager, 'for_profile') else manager
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
    context = {'sources': index.sources, 'definitions': definitions, 'settings': domain_settings,
               'credential_profile': credential_profile}
    pending, estimates = list(pinned), []
    while pending:
        planned = pack_request(pending, profile, context)
        estimates.append(planned)
        pending = [p for p in pending if p.part_id not in planned.part_ids]
    if cancelled and cancelled():
        raise InterruptedError('cancelled')
    preview = {'valid': True, 'mode': 'ai', 'source_kind': next((p.source_kind for p in parts), ''),
        'files': len(prepared.sources), 'parts': len(parts), 'units': len(parts), 'blocked': [],
        'routes': {'project_lineage': [{'provider': profile.provider, 'model': profile.model}]},
        'estimated_requests': len(estimates), 'max_provider_attempts': len(estimates),
        'estimated_input_tokens': sum(p.budget.input_count for p in estimates),
        'estimated_output_tokens': sum(p.reserved_output for p in estimates), 'limits': asdict(limits),
        'estimate_method': estimates[0].budget.count_method if estimates else '',
        'packing': [p.packing for p in estimates],
        'allocation': allocation,
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
    registered, associated, stage, summary = False, False, 'planning', {}
    counts, usage_known = Counter(), True
    started = monotonic()
    prior_seconds = 0.
    replay_attempts = []
    if progress and hasattr(progress, 'bind_run'):
        progress.bind_run(run_id)
    def activity(kind, **detail):
        summary['current_activity'] = kind
        summary['activity'] = [*summary.get('activity', []), {'kind': kind, 'at': time(), **detail}][-30:]
        if registered:
            save_run(store, workspace, run_id, mode='ai', status=stage,
                summary={'activity': summary['activity'], 'current_activity': kind, 'stage': stage})
    def update(name):
        if progress:
            progress(0., name)
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
            save_run(store, workspace, run_id, mode='ai', status='planning', summary=summary)
            associated = True
            try:
                def preparing(name, completed, total):
                    if cancelled and cancelled():
                        raise InterruptedError('cancelled')
                    if progress:
                        progress(completed / max(1, total), f'{name}: {completed} / {total}')
                update('Preparing selected sources')
                prepared, parts, route, context, preview = _prepare(store, workspace, request, manager, cancelled,
                    preparation_progress=preparing)
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
                recovery = recover_pipeline(store, workspace, run_id)
                unknown = []
                completed = {r['unit_id'] for r in store.rows("SELECT unit_id FROM ai_analysis_units WHERE workspace_id=? AND run_id=? AND status='completed' AND context_hash='extraction5'", [workspace, run_id])}
                for attempt in recovery['unknown']:
                    req = store.rows('SELECT unit_ids,details FROM ai_analysis_requests WHERE batch_id=?', [attempt['batch_id']])[0]
                    request_details = json.loads(req['details'])
                    membership = set(json.loads(req['unit_ids']))
                    if attempt['status'] == 'received' and membership <= completed:
                        # Successful checkpoints are authoritative even when the
                        # response body was never retained or has since expired.
                        for part_id in membership:
                            summary.get('recovery_queue', {}).pop(part_id, None)
                            summary.get('unresolved_work', {}).pop(part_id, None)
                        with store.transaction():
                            save_run(store, workspace, run_id, mode='ai', status='planning', summary=summary)
                            store.execute("UPDATE ai_analysis_requests SET status='processed',details=? WHERE batch_id=?",
                                [json.dumps({**request_details, 'outcome': {'saved': sorted(membership), 'missing': [],
                                    'invalid': {}, 'unresolved': []}}), attempt['batch_id']])
                        continue
                    fingerprint = request_details.get('fingerprint')
                    retained = load_replayable_response(store, workspace, run_id, attempt['attempt_id'],
                        expected_fingerprint=fingerprint)
                    if retained['content'] is not None and fingerprint:
                        try:
                            raw, usage, metadata = decode_provider_response(profile.provider,
                                decode_wire_response(retained['content'], retained['format']), requested_model=profile.model)
                            raw = manager.redact(raw)
                        except (ValueError, ProviderError):
                            retained = {'reason': 'invalid_retained_response', 'content': None}
                        else:
                            finish_attempt(store, workspace, run_id, attempt['attempt_id'], 'received', details={**metadata, 'usage': usage})
                            replay_attempts.append({'attempt': attempt, 'part_ids': json.loads(req['unit_ids']),
                                'raw': raw, 'metadata': response_metadata(metadata, usage), 'usage': usage})
                            continue
                    summary.setdefault('replay_unavailable', {})[attempt['attempt_id']] = retained['reason']
                    unknown.append(attempt)
                # An intact response checkpoint can resolve a dispatch whose
                # receipt/usage write was interrupted. Other unknowns stay unknown.
                usage_known = all(json.loads(a['details']).get('usage_known') is True
                    for a in store.rows('SELECT details FROM ai_analysis_attempts WHERE workspace_id=? AND run_id=?', [workspace, run_id]))
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
                pinned_index = build_context_index(prepared, [])
                for part in parts:
                    context['definitions'][part.part_id] = restore_part_context(pinned_index, part)
                if summary.pop('_retry_partial_publication', False):
                    for part_id in summary.get('unresolved_work', {}):
                        state = summary.get('recovery_queue', {}).get(part_id, {})
                        state.update(retry_baseline=state.get('failures', 0), not_before=time())
                    summary['unresolved_work'] = {}
            from dataforge.ai_pipeline_store import reported_totals
            for key, value in reported_totals(store, workspace, run_id).items():
                counts[key] = value
            counts['files'], counts['parts'] = len(prepared.sources), len(parts)
            counts['processed'] = len(store.rows("SELECT unit_id FROM ai_analysis_units WHERE workspace_id=? AND run_id=? AND status='completed' AND context_hash='extraction5'",
                                                  [workspace, run_id]))
            summary.update(protocol_version=5, request=request.model_dump(), pin=pin, parts=[p.model_dump() for p in parts],
                           allocation=preview['allocation'],
                           retry_policy={'unknown_retries': profile.unknown_retries, 'shared_retries': profile.retries})
            summary.setdefault('initial_estimate', {'requests': preview['estimated_requests'], 'input_tokens': preview['estimated_input_tokens']})
            save_run(store, workspace, run_id, mode='ai', status='extracting', manifest=prepared.manifest,
                     configuration=prepared.settings, summary=summary)
            registered = True

        def checkpoint():
            counts['processed'] = len(store.rows("SELECT unit_id FROM ai_analysis_units WHERE workspace_id=? AND run_id=? AND status='completed' AND context_hash='extraction5'", [workspace, run_id]))
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
            bound = manager.for_profile(pid, context['credential_profile']) if hasattr(manager, 'for_profile') else manager
            if profile.key_env and not bound.resolve(profile.key_env):
                raise ValueError('Configured provider credential is unavailable')

        def execute(work, work_context):
            nonlocal usage_known
            if not work:
                return set()
            def completed_parts():
                records = {r['unit_id']: json.loads(r['result']) for r in store.rows(
                    "SELECT unit_id,result FROM ai_analysis_units WHERE workspace_id=? AND run_id=? AND status='completed' AND context_hash='extraction5'",
                    [workspace, run_id])}
                for p in work:
                    if p.part_id in records and records[p.part_id].get('part') != p.model_dump():
                        raise ValueError('source_or_configuration_changed')
                return set(records)
            saved = completed_parts()
            replays = [r for r in replay_attempts if set(r['part_ids']) <= {p.part_id for p in work}]
            summary['reused_part_ids'] = sorted(set(summary.get('reused_part_ids', [])) | ({p.part_id for p in work} & saved))
            checkpoint()
            unresolved_work = summary.setdefault('unresolved_work', {})
            pending = [p for p in work if p.part_id not in saved and p.part_id not in unresolved_work]
            errors = summary.setdefault('item_failures', {})
            queue = summary.setdefault('recovery_queue', {})
            def split_pending(parent, reason):
                state = queue.setdefault(parent.part_id, {})
                children = split_truncated_part(parent, context['sources'][parent.file_id], state.get('split_depth', 0))
                if not children:
                    return False
                save_unit_result(store, workspace, run_id, parent.part_id, file_id=parent.file_id,
                    content_hash=parent.content_hash, status='superseded', result={'contract': 'superseded5',
                        'children': [p.part_id for p in children]})
                state.update(recovery_action=reason, children=[p.part_id for p in children])
                summary.setdefault('split_parts', {})[parent.part_id] = state
                queue.pop(parent.part_id, None)
                parts.remove(parent)
                parts.extend(children)
                pending.remove(parent)
                pending.extend(children)
                for child in children:
                    queue[child.part_id] = {'split_depth': 1, 'parent': parent.part_id}
                    work_context['definitions'][child.part_id] = work_context['definitions'].get(parent.part_id, [])
                summary['parts'] = [p.model_dump() for p in parts]
                counts['parts'] = len(parts)
                return True
            while pending or replays:
                saved.update(completed_parts())
                pending = [p for p in pending if p.part_id not in saved]
                if not pending and not replays:
                    break
                check()
                replay = replays.pop(0) if replays else None
                truncated = False
                ready = [p for p in pending if not queue.get(p.part_id, {}).get('budget_blocked') and
                         queue.get(p.part_id, {}).get('not_before', 0) <= time()]
                if not ready and not replay:
                    retryable = [p for p in pending if not queue.get(p.part_id, {}).get('budget_blocked')]
                    if not retryable:
                        raise TimeoutError('recovery_request_exceeds_budget')
                    due = min(queue[p.part_id]['not_before'] for p in retryable)
                    reason = queue[pending[0].part_id]['code']
                    update(f'Waiting to retry {pending[0].work_kind}: {reason}. Cancel remains available.')
                    activity('recovery', part_ids=[p.part_id for p in pending], reason=reason)
                    checkpoint()
                    recovery_wait(max(.01, due - time()), check)
                    continue
                # Fresh work goes first. A failed batch gets at most half its old
                # width on the next pass; singleton failures remain isolated.
                if replay:
                    ready = [p for p in work if p.part_id in replay['part_ids']]
                fresh = [p for p in ready if not queue.get(p.part_id, {}).get('failures')]
                eligible = fresh or ready
                width = min(queue.get(p.part_id, {}).get('batch_limit', len(eligible)) for p in eligible)
                feedback = {p.part_id: {k: queue[p.part_id][k] for k in ('code', 'path', 'attempt')}
                            for p in eligible if queue.get(p.part_id, {}).get('failures')}
                if replay:
                    from types import SimpleNamespace
                    scheduled = ready
                    batch_id = replay['attempt']['batch_id']
                    planned = SimpleNamespace(reserved_output=replay['attempt']['reserved_output'])
                else:
                    try:
                        planned = pack_request(eligible[:width], profile, {**work_context, 'recovery_feedback': feedback})
                    except ValueError as exc:
                        # Feedback/overlap is sized in the actual body, too. This is
                        # concrete size evidence, not permission for blind halving.
                        if str(exc) not in {'complete_request_exceeds_input_budget', 'part_output_estimate_exceeds_budget',
                                            'explicit_disclosure_limit_exceeded'}:
                            raise
                        parent = eligible[0]
                        with store.transaction():
                            if not split_pending(parent, 'split_request_budget'):
                                queue.setdefault(parent.part_id, {}).update(code='recovery_request_exceeds_budget',
                                    budget_blocked=True, recovery_action='change_request_budget')
                            checkpoint()
                        continue
                    scheduled = [p for p in pending if p.part_id in planned.part_ids]
                    batch_id = stable_id(run_id, planned.serialized_payload)
                    save_request(store, workspace, run_id, batch_id, list(planned.part_ids),
                        details={'work_kind': scheduled[0].work_kind, 'budget': asdict(planned.budget),
                                 'packing': planned.packing, 'fingerprint': _hash({'pin': pin, 'payload': planned.serialized_payload}),
                                 'batch_number': len(store.rows('SELECT batch_id FROM ai_analysis_requests WHERE workspace_id=? AND run_id=?', [workspace, run_id])) + 1})
                ticket = None
                diagnostics, metadata, usage = {}, {}, {}
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
                        details={'started_at': time(), 'attempt_number': len(history) + 1, 'cycle_attempt': len(cycle) + 1,
                                 'attempt_limit': profile.retries + 1, 'batch_number': request_details.get('batch_number', 1), 'timeouts': {
                            'connect': profile.connect_timeout, 'read': None if profile.wait_until_stopped else (profile.read_timeout or profile.timeout),
                            'write': profile.timeout, 'pool': profile.connect_timeout}})
                    physical_started = monotonic()
                    if progress and hasattr(progress, 'reasoning'):
                        with connection_scope(bound):
                            progress.reasoning(run_id, ticket)
                    activity('dispatch', request_id=batch_id, attempt_id=ticket)
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
                        activity('recovery', request_id=batch_id, attempt_id=ticket, outcome=detail['failure_category'])
                        if detail['retry_scheduled']:
                            update(recovery_message({'last_failure': detail}))
                        checkpoint()
                bound = manager.for_profile(pid, context['credential_profile']) if hasattr(manager, 'for_profile') else manager
                def capture(kind, body, secrets=(), **options):
                    if ticket:
                        eligible = False
                        if kind == 'output' and not options.get('unavailable'):
                            try:
                                decode_provider_response(profile.provider,
                                    decode_wire_response(body, options.get('wire_format', 'json')), requested_model=profile.model)
                            except (ValueError, ProviderError, UnicodeError):
                                pass
                            else:
                                eligible = True
                        capture_payload(store, workspace, run_id, ticket, kind, body, secrets,
                            replay_fingerprint=_hash({'pin': pin, 'payload': planned.serialized_payload}),
                            replay_eligible=eligible, **options)
                def thinking(delta='', state='streaming'):
                    if ticket and progress and hasattr(progress, 'reasoning'):
                        progress.reasoning(run_id, ticket, delta, state)
                try:
                    if replay:
                        ticket = replay['attempt']['attempt_id']
                        raw, usage, metadata = replay['raw'], replay['usage'], replay['metadata']
                        activity('replay', request_id=batch_id, attempt_id=ticket)
                    else:
                        with connection_scope(bound), request_slot(store.home, workspace, 1), Adapter(profile,
                                transport=transport, cancelled=cancelled, before_attempt=before_attempt, check=check,
                                attempt_observer=observed_failure,
                                wire_observer=capture,
                                # Keep live streaming off pending realistic wire-size qualification.
                                stream_analysis=False, reasoning_observer=thinking,
                                retry_unknown_transports=bool(profile.unknown_retries)) as adapter:
                            raw, usage = adapter.complete(planned.system, planned.user)
                            thinking(state='finished')
                            metadata = response_metadata(adapter.completion_metadata, usage)
                            usage = metadata['usage']
                        if ticket:
                            finish_attempt(store, workspace, run_id, ticket, 'received',
                                details={**metadata, 'usage': usage})
                        activity('response', request_id=batch_id, attempt_id=ticket)
                        update('Validating AI response')
                        usage_known &= metadata.get('usage_known', False)
                        for key, aliases in {'input_tokens': ('input_tokens', 'prompt_tokens', 'promptTokenCount'),
                                             'output_tokens': ('output_tokens', 'completion_tokens', 'candidatesTokenCount')}.items():
                            counts[key] += next((usage[a] for a in aliases if type(usage.get(a)) is int), 0)
                    try:
                        truncated = bool(metadata.get('truncated'))
                        valid, invalid = decode_extractions(raw, scheduled, diagnostics=diagnostics,
                            allow_truncated=truncated)
                    except ValueError as exc:
                        code = str(exc) if str(exc) in {'invalid_extraction_json', 'invalid_extraction_envelope',
                                                     'truncated_extraction_response'} else 'invalid_extraction_response'
                        valid, invalid = {}, {p.part_id: code for p in scheduled}
                except ProviderError as exc:
                    thinking(state='interrupted')
                    if ticket and store.rows('SELECT status FROM ai_analysis_attempts WHERE attempt_id=?', [ticket])[0]['status'] == 'dispatched':
                        observed_failure({'failure_category': 'invalid_response', 'outcome': 'known',
                                          'retry_scheduled': False, 'allowance_exhausted': False})
                    if exc.unknown and not profile.unknown_retries:
                        raise TimeoutError('unknown_inflight_request_requires_explicit_retry') from None
                    if cancelled and cancelled():
                        raise InterruptedError('cancelled') from None
                    failure = summary.get('last_failure', {})
                    category = failure.get('failure_category', 'invalid_response')
                    if category not in {'pre_send', 'transport_unknown', 'invalid_response'} and not (
                            category == 'http_failure' and (failure.get('http_status') == 429 or
                                                          (failure.get('http_status') or 0) >= 500)):
                        raise TimeoutError(category) from None
                    valid, invalid = {}, {p.part_id: category for p in scheduled}
                except TimeoutError as exc:
                    # A previous process may have used up this pass. Do not
                    # renew its allowance on resume; defer a new durable pass.
                    if str(exc) != 'batch_retry_allowance_exhausted':
                        raise
                    valid, invalid = {}, {p.part_id: 'batch_retry_allowance_exhausted' for p in scheduled}
                activity('validation', request_id=batch_id, attempt_id=ticket)
                for part in scheduled:
                    if part.part_id in saved:
                        continue
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
                        except ValueError as exc:
                            diagnostics[part.part_id] = validation_failure(exc)
                            invalid[part.part_id] = diagnostics[part.part_id]['code']
                            item = None
                        if item is not None:
                            # Storage failures are blockers, not model repairs.
                            save_part_extraction(store, workspace, run_id, part, item, record_id=ticket)
                            counts['processed'] += 1
                            saved.add(part.part_id)
                            activity('persistence', request_id=batch_id, part_id=part.part_id)
                            check()
                    if part.part_id not in saved:
                        errors[part.part_id] = errors.get(part.part_id, 0) + 1
                counts['requests'], counts['reserved_output_tokens'] = attempt_totals(store, workspace, run_id)
                failed = [p for p in scheduled if p.part_id not in saved]
                request_diagnostics = []
                for part in failed:
                    state = queue.setdefault(part.part_id, {})
                    number = state.get('failures', 0) + 1
                    detail = diagnostics.get(part.part_id, {'code': invalid.get(part.part_id, 'missing_extraction_item'), 'path': ''})
                    state.update(failures=number, attempt=number, code=detail['code'], path=detail['path'],
                        batch_limit=1 if number - state.get('retry_baseline', 0) >= 2 else max(1, len(scheduled) // 2),
                        not_before=time() + min(60, 2 ** min(number - 1, 6)),
                        recovery_action='isolate' if len(scheduled) <= 2 else 'smaller_batch')
                    history = batch_attempts(store, workspace, run_id, batch_id)
                    request_diagnostics.append({**detail, 'stage': stage, 'request_id': batch_id,
                        'part_id': part.part_id, 'attempt_number': len(history), 'recovery_pass': number,
                        'recovery_action': state['recovery_action'], 'response': metadata,
                        'reserved_output_tokens': planned.reserved_output})
                if '__envelope__' in diagnostics:
                    request_diagnostics.append({**diagnostics['__envelope__'], 'stage': stage, 'request_id': batch_id,
                        'part_id': None, 'attempt_number': len(batch_attempts(store, workspace, run_id, batch_id)),
                        'recovery_action': 'ignore_unknown_id', 'response': metadata,
                        'reserved_output_tokens': planned.reserved_output})
                if '__truncation__' in diagnostics:
                    request_diagnostics.append({**diagnostics['__truncation__'], 'stage': stage,
                        'request_id': batch_id, 'part_id': None,
                        'attempt_number': len(batch_attempts(store, workspace, run_id, batch_id)),
                        'recovery_action': 'complete_items_preserved', 'response': metadata,
                        'reserved_output_tokens': planned.reserved_output})
                # Reduce a truncated multi-item batch first. A singleton can
                # split once, with explicit parent/children and exact core ranges.
                if truncated and len(scheduled) == 1:
                    for parent in list(failed):
                        with store.transaction():
                            if split_pending(parent, 'split_truncated_source'):
                                request_diagnostics[0]['recovery_action'] = 'split_truncated_source'
                                failed.remove(parent)
                                checkpoint()
                for part in list(failed):
                    state = queue[part.part_id]
                    if state['failures'] - state.get('retry_baseline', 0) >= 3:
                        from dataforge.ai_analysis_models import PartExtraction
                        # Host-owned failure record, never a model no_operations
                        # result. Its source range remains explicitly unprocessed.
                        stub = PartExtraction(part_id=part.part_id, coverage='partial', omitted=True,
                            unresolved=['required_work_unresolved:' + state['code']])
                        save_part_extraction(store, workspace, run_id, part, stub, status='unresolved')
                        state['recovery_action'] = 'retry_after_partial_publication'
                        unresolved_work[part.part_id] = {'file_id': part.file_id, 'work_kind': part.work_kind,
                            'code': state['code'], 'failures': state['failures']}
                        for diagnostic in request_diagnostics:
                            if diagnostic.get('part_id') == part.part_id:
                                diagnostic['recovery_action'] = state['recovery_action']
                        failed.remove(part)
                for part in scheduled:
                    if part.part_id in saved:
                        queue.pop(part.part_id, None)
                        unresolved_work.pop(part.part_id, None)
                details = json.loads(store.rows('SELECT details FROM ai_analysis_requests WHERE batch_id=?', [batch_id])[0]['details'])
                # Atomic queue/status checkpoint: an interrupted recovery pass
                # cannot look processed while losing its delay/feedback state.
                with store.transaction():
                    store.execute("UPDATE ai_analysis_requests SET status='processed',details=? WHERE batch_id=?",
                        [json.dumps({**details, 'diagnostics': request_diagnostics,
                            'outcome': {'saved': [p.part_id for p in scheduled if p.part_id in saved],
                                'missing': [p.part_id for p in failed],
                                'invalid': invalid, 'unresolved': [p.part_id for p in scheduled if p.part_id in unresolved_work]}}), batch_id])
                    checkpoint()
                if ticket:
                    with connection_scope(bound):
                        capture_payload(store, workspace, run_id, ticket, 'decoded', json.dumps({
                            'decoded': {key: value.model_dump() for key, value in valid.items()},
                            'validated': [p.part_id for p in scheduled if p.part_id in saved],
                            'validation_errors': invalid, 'diagnostics': request_diagnostics,
                            'recovery': {p.part_id: queue[p.part_id] for p in scheduled if p.part_id in queue}
                        }, ensure_ascii=False).encode('utf-8'))
                pending = [p for p in pending if p.part_id not in saved and p.part_id not in unresolved_work and p not in failed] + failed
            return {p.part_id for p in work if p.part_id in unresolved_work}

        stage = 'extracting'
        update('Extracting file contents')
        extraction_unresolved = execute(parts, context)
        initial = {p.part_id: (p, r) for p, r in load_file_parts(store, workspace, run_id) if p.work_kind == 'extraction'}
        if 'completion_work' not in summary and not extraction_unresolved:
            frozen = build_context_index(prepared, [r for _, r in initial.values()])
            works = plan_context_completion(list(initial.values()), frozen)
            summary['completion_work'] = [{'part': w.part.model_dump(), 'original': w.original_part_id,
                'definitions': w.context.wire, 'catalog_revision': w.catalog_revision} for w in works]
            checkpoint()
        works = summary.get('completion_work', [])
        stage = 'validating'
        completion_context = {**context, 'definitions': {w['part']['part_id']: w['definitions'] for w in works},
            'work_inputs': {w['part']['part_id']: initial[w['original']][1].model_dump() for w in works}}
        bounded = []
        for work in works:
            part = FilePart.model_validate(work['part'])
            try:
                pack_request([part], profile, {**completion_context,
                    'recovery_feedback': {part.part_id: RECOVERY_FEEDBACK_RESERVE}})
                bounded.append(part)
            except ValueError:
                initial[work['original']][1].unresolved.append('completion_context_exceeds_budget')
        update('Completing affected source context')
        completion_unresolved = execute(bounded, completion_context)
        saved = {p.part_id: r for p, r in load_file_parts(store, workspace, run_id)}
        for work in works:
            if work['part']['part_id'] in completion_unresolved:
                initial[work['original']][1].unresolved.append('context_completion_unresolved')
            elif work['part']['part_id'] in saved:
                original, item = initial[work['original']]
                initial[original.part_id] = (original, merge_extraction_revision(item, saved[work['part']['part_id']]))
        stage = 'consolidating'
        activity('consolidation')
        checkpoint()
        file_work, consolidation_inputs, consolidation_parts = {}, {}, []
        file_parts_by_id = {s.file_id: [(p, r) for p, r in initial.values() if p.file_id == s.file_id]
                            for s in prepared.sources if s.source_kind in {'sql', 'sas', 'dbt'}}
        if 'consolidation_work' not in summary and not (extraction_unresolved or completion_unresolved):
            # Before this queue existed, group fitting did not reserve feedback.
            # Recreate that fitting only for an already-started consolidation
            # stage, retaining its stable IDs, attempts and saved supersessions.
            prior_groups = any(p.work_kind == 'consolidation' for p, _ in load_file_parts(store, workspace, run_id)) or any(
                json.loads(row['details']).get('work_kind') == 'consolidation' for row in store.rows(
                    'SELECT details FROM ai_analysis_requests WHERE workspace_id=? AND run_id=?', [workspace, run_id]))
            frozen_work = []
            for file_parts in file_parts_by_id.values():
                for group in plan_file_consolidation(file_parts, profile, context=context, reserve_feedback=not prior_groups):
                    frozen_work.append({'part': group.part.model_dump(), 'overflow': group.overflow,
                        'operation_hashes': [_hash(op) for op in group.inputs['operations']],
                        'part_ids': group.inputs['part_ids']})
            summary['consolidation_work'] = frozen_work
            checkpoint()
        # Pin membership as references to existing durable facts, not another
        # copy of their potentially large operation/column payloads.
        operations_by_hash = {_hash(op.model_dump()): op.model_dump()
                              for _, result in initial.values() for op in result.operations}
        groups_by_file = {}
        for frozen_group in summary.get('consolidation_work', []):
            part = FilePart.model_validate(frozen_group['part'])
            if any(key not in operations_by_hash for key in frozen_group['operation_hashes']):
                raise ValueError('pinned_consolidation_inputs_unavailable')
            group = ConsolidationWork(part, {'operations': [operations_by_hash[key] for key in frozen_group['operation_hashes']],
                'part_ids': frozen_group['part_ids']}, frozen_group['overflow'])
            groups_by_file.setdefault(part.file_id, []).append(group)
        for source in prepared.sources:
            if source.source_kind not in {'sql', 'sas', 'dbt'}:
                continue
            file_parts = file_parts_by_id[source.file_id]
            groups = groups_by_file.get(source.file_id, [])
            file_work[source.file_id] = (file_parts, groups)
            consolidation_parts.extend(g.part for g in groups if not g.overflow)
            consolidation_inputs.update({g.part.part_id: g.inputs for g in groups if not g.overflow})
        execute(consolidation_parts, {**context, 'work_inputs': consolidation_inputs})
        for source in prepared.sources:
            if source.file_id not in file_work:
                continue
            file_parts, groups = file_work[source.file_id]
            consolidated = [r for p, r in load_file_parts(store, workspace, run_id, source.file_id) if p.work_kind == 'consolidation']
            final = assemble_file_extraction(source, file_parts, consolidated,
                provenance={'profile': execution_profile(profile), 'prompt': pin['protocol'], 'schema': 5})
            final.processed = not any(p.part_id in extraction_unresolved for p, _ in file_parts)
            if (extraction_unresolved or completion_unresolved) and len(file_parts) > 1:
                final.unresolved.append('enrichment_deferred_until_required_work_recovery')
                final.semantic_coverage = 'partial'
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
        counts['unresolved_parts'] = len(summary.get('unresolved_work', {}))
        counts['unprocessed_files'] = sum(not f.processed for f in files)
        update('Publishing validated lineage')
        activity('publication', outcome='started')
        with store.analysis_lock, store.transaction():
            check()
            _current(store, workspace, prepared, expected, full=True)
            published = publish_analysis_results(store, workspace, results, prepared.settings,
                {'analyzed': len(files), 'cached': 0, 'dbt_projects': dbt_projects}, cancelled=cancelled)
            counts.update({k: published[k] for k in ('analyzed', 'cached', 'assets', 'edges')})
            report = AnalysisReport(run_id=run_id, mode='ai', status='committed', complete=False,
                counts=dict(counts), usage_known=usage_known,
                reasons=['semantic_coverage_not_proven', *(['required_work_unresolved'] if counts['unresolved_parts'] else [])])
            if counts['unresolved_parts']:
                # Only this run's own publication advances its pinned predecessor.
                # Another build, or a source/config change, still makes retry stale.
                pin['prior'] = published['run_id']
            save_run(store, workspace, run_id, mode='ai', status='committed', analysis_run_id=published['run_id'],
                accepted_results=results, summary={**summary, **report.model_dump()})
        summary['activity'] = [*summary.get('activity', []), {'kind': 'publication', 'at': time(), 'outcome': 'committed'}][-30:]
        save_run(store, workspace, run_id, mode='ai', status='committed', summary={'activity': summary['activity'], 'current_activity': 'publication'})
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
        if registered or associated or status == 'stale':
            summary['active_seconds'] = prior_seconds + monotonic() - started
            save_run(store, workspace, run_id, mode='ai', status=status,
                summary={**summary, **report.model_dump(), 'stage': stage})
        return report
    except Exception:
        if registered or associated:
            save_run(store, workspace, run_id, mode='ai', status='failed', summary={'reasons': ['internal_error'], 'stage': stage})
        raise


def analysis_report(store, workspace, run_id=None, *, include_source=False):
    report = load_analysis_report(store, workspace, run_id, include_source=include_source)
    if report is None:
        raise ValueError('Analysis report not found')
    report.pop('configuration', None)
    report['recent_requests'] = [{**row, 'details': json.loads(row['details'])} for row in store.rows(
        'SELECT batch_id,status,details FROM ai_analysis_requests WHERE workspace_id=? AND run_id=? ORDER BY rowid DESC LIMIT 20',
        [workspace, report['run_id']])]
    return report
