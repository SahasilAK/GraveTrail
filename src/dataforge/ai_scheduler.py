"""Bounded provider workers with owner-thread authorization and durable dispatch.

Workers receive prompt/profile snapshots and a message bridge, never a Store.
The coordinator continues servicing admissions while responses are outstanding.
"""
from __future__ import annotations

import hashlib
import json
import queue
import random
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import copy
from dataclasses import dataclass, field

from dataforge.ai_analysis_store import save_run
from dataforge.ai_batching import batch_prompt, decode_batch_response, next_batch_width, pack_batch
from dataforge.ai_budget import estimate_tokens, project_profile, request_allowance
from dataforge.ai_pipeline_store import begin_attempt, finish_attempt, save_request
from dataforge.ai_rate_limits import QUOTAS, quota_scope, retry_delay
from dataforge.ai_wire import decode_project_result
from dataforge.connections import connection_scope
from dataforge.llm import (
    PROJECT_PROTOCOLS,
    Adapter,
    ProviderError,
    analysis_prompt,
    analysis_routes,
    response_object,
)
from dataforge.llm_resources import request_slot


@dataclass
class AdmissionMessage:
    event: threading.Event = field(default_factory=threading.Event)
    timeout: float = 0
    error: Exception | None = None
    ticket: str = ''
    stop: threading.Event | None = None


@dataclass(frozen=True)
class WorkerRequest:
    profile: object
    system: str
    user: str
    connections: object
    transport: object
    cancelled: object


@dataclass(frozen=True)
class WorkerOutcome:
    raw: str = ''
    usage: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    error: str = ''
    status: int | None = None
    limits: dict = field(default_factory=dict)
    unknown: bool = False


def dispatch_provider_request(request, admissions, message):
    """One physical attempt. Retries/fallback/admission belong to the owner."""
    status, limits = None, {}
    def admit(profile):
        admissions.put(message)
        while not message.event.wait(.1):
            if message.stop is not None and message.stop.is_set():
                raise InterruptedError('coordinator_stopped')
        if message.error:
            raise message.error
        return message.timeout
    def observe(code, snapshot):
        nonlocal status, limits
        status, limits = code, snapshot
    try:
        with connection_scope(request.connections), Adapter(
                request.profile.model_copy(update={'retries': 0}), request.transport,
                cancelled=request.cancelled, before_attempt=admit, response_observer=observe,
                retry_unknown_transports=False) as adapter:
            raw, usage = adapter.complete(request.system, request.user)
            return WorkerOutcome(raw=raw, usage=usage, metadata=adapter.completion_metadata,
                                 status=status, limits=limits)
    except (ProviderError, ValueError, TimeoutError, InterruptedError) as exc:
        return WorkerOutcome(error=request.connections.redact(str(exc))[:500], status=status,
                             limits=limits, unknown=bool(message.ticket and (status is None or getattr(exc, 'unknown', False))))


@contextmanager
def _workers(parallel, stop, inflight):
    pool = ThreadPoolExecutor(max_workers=parallel, thread_name_prefix='lineage-provider')
    try:
        yield pool
    finally:
        stop.set()
        pool.shutdown(wait=True, cancel_futures=True)
        for active in inflight.values():
            active['slot'].__exit__(None, None, None)


def run_pending_requests(store, workspace, run_id, units, execution, *, contexts, accept, progress=None, record_usage=None):
    """Extract pending units; accepted item callbacks execute only on the owner thread."""
    routes = analysis_routes(store, workspace, 'project_lineage')
    parallel = min(execution.request.max_parallel_requests or 4,
                   store.setting(workspace, 'llm_concurrency', 1))
    width = min(8, execution.request.max_files_per_request or 1)
    clean_streak, repairs, completed = 0, {}, set()
    pending = [(tuple(units), 0, 0, 0.)]
    inflight, waiting, admissions = {}, [], queue.Queue()
    fatal, unknown = None, False
    manager = execution.connections
    if manager is None:
        from dataforge.connections import current_connections
        manager = current_connections()

    def state(status, **detail):
        existing = store.rows('SELECT summary FROM ai_analysis_runs WHERE workspace_id=? AND run_id=?', [workspace, run_id])
        counts = json.loads(existing[0]['summary']).get('counts', {})
        save_run(store, workspace, run_id, mode=execution.request.mode, status=status,
            summary={'counts': {**counts, 'requests': execution.prior_requests + execution.attempts,
                     'reserved_output_tokens': execution.prior_reserved + execution.reserved_output_tokens},
                     'active_seconds': execution.active_seconds, **detail})
        if progress:
            progress(.1 + .7 * len(completed) / max(1, len(units)), status.replace('_', ' '))

    stop = threading.Event()
    with _workers(parallel, stop, inflight) as pool:
        while pending or inflight or waiting:
            if execution.cancelled and execution.cancelled():
                fatal = InterruptedError('cancelled')
            try:
                execution.check()
            except TimeoutError as exc:
                if execution.request.auto_continue and str(exc) == 'deadline_exceeded' and not any(v['message'].ticket for v in inflight.values()):
                    execution.rollover()
                else:
                    fatal = exc
            while not admissions.empty():
                message = admissions.get_nowait()
                waiting.append(message)
            for message in list(waiting):
                active = next((v for v in inflight.values() if v['message'] is message), None)
                if active is None:
                    continue
                profile = active['profile']
                try:
                    if fatal:
                        raise fatal
                    now = time.time()
                    wait_until = QUOTAS.admit(quota_scope(profile), estimated_input=active['estimated_input'],
                                              reserved_output=profile.max_tokens, now=now)
                    if wait_until > now:
                        state('waiting_provider', wait_until=wait_until)
                        continue
                    if (execution.attempts >= execution.request.max_provider_attempts
                            or execution.reserved_output_tokens + profile.max_tokens > execution.request.max_output_tokens_total):
                        if not execution.request.auto_continue:
                            raise TimeoutError('execution_budget_reached')
                        if any(v['message'].ticket for v in inflight.values()):
                            continue
                        execution.rollover()
                    message.timeout = execution.before_attempt(profile)
                    message.ticket = begin_attempt(store, workspace, run_id, active['batch_id'], profile.max_tokens,
                        details={'lifetime_attempts': execution.prior_requests + execution.attempts,
                                 'lifetime_reserved_output': execution.prior_reserved + execution.reserved_output_tokens})
                    state('extracting', inflight=False)
                except (ValueError, TimeoutError, InterruptedError) as exc:
                    message.error = fatal = exc
                message.event.set()
                waiting.remove(message)
            for future, active in list(inflight.items()):
                if not future.done():
                    continue
                outcome = future.result()
                active['slot'].__exit__(None, None, None)
                del inflight[future]
                ticket = active['message'].ticket
                if ticket:
                    finish_attempt(store, workspace, run_id, ticket,
                                   'unknown' if outcome.unknown else 'known_failure' if outcome.error else 'received',
                                   details={'quota_scope': quota_scope(active['profile']), 'limits': outcome.limits})
                if outcome.limits:
                    QUOTAS.observe(quota_scope(active['profile']), outcome.limits)
                if not ticket:
                    fatal = active['message'].error or ValueError(outcome.error)
                    continue
                if record_usage:
                    record_usage(outcome)
                record_id = uuid.uuid4().hex
                details = {'unit_ids': [u.unit_id for u in active['units']], 'attempt_id': ticket,
                    'reason': outcome.error, 'attempts': 1, 'requested_model': active['profile'].model,
                    'resolved_model': outcome.metadata.get('resolved_model'),
                    'usage_known': bool(outcome.metadata.get('usage_known')), 'result': None,
                    'schema_version': 'batch-1' if len(active['units']) > 1 else PROJECT_PROTOCOLS['project_lineage'][0]}
                if store.setting(workspace, 'llm_history', False):
                    details.update(context=active['user'], response=outcome.raw)
                with store.transaction():
                    store.execute('INSERT INTO prompt_versions VALUES (?,?,?) ON CONFLICT DO NOTHING',
                        [active['prompt_hash'], 'project_lineage', active['prompt_version']])
                    store.execute('''INSERT INTO llm_records(record_id,workspace_id,profile_id,task,file_id,start_line,
                        prompt_hash,provider,model,outcome,duration,usage,details) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        [record_id, workspace, routes[active['route']][0], 'project_lineage', active['units'][0].file_id,
                         active['units'][0].first, active['prompt_hash'], active['profile'].provider, active['profile'].model,
                         'quarantined' if outcome.error else 'validated', time.monotonic() - active['started'],
                         json.dumps(manager.sanitize(outcome.usage)), json.dumps(manager.sanitize(details))])
                if outcome.unknown:
                    unknown = True
                    continue
                batch = active['units']
                if outcome.error:
                    route_index, retry = active['route'], active['retry']
                    configured = routes[route_index][1]
                    if outcome.error in {'provider_credits_exhausted', 'provider_daily_quota_exhausted'}:
                        fatal = TimeoutError(outcome.error)
                        continue
                    if outcome.status == 429 or (outcome.status and outcome.status >= 500):
                        if retry < configured.retries:
                            delay = max(outcome.limits.get('wait_until', 0) - time.time(),
                                        retry_delay(retry, {}, now=time.time(), jitter=random.random() * .2))
                            pending.append((batch, route_index, retry + 1, time.time() + delay))
                            continue
                        if route_index + 1 < len(routes):
                            pending.append((batch, route_index + 1, 0, 0.))
                            continue
                    fatal = ValueError('provider_quota_or_request_failed' if outcome.status == 429 else outcome.error)
                    continue
                good, errors = {}, {}
                try:
                    if outcome.metadata.get('truncated'):
                        raise ValueError('truncated_batch')
                    if len(batch) == 1:
                        good[batch[0].unit_id] = decode_project_result('project_lineage', response_object(outcome.raw),
                                                                      batch[0], settings=execution.settings)
                    else:
                        good, errors = decode_batch_response(outcome.raw, batch, settings=execution.settings)
                except ValueError:
                    errors = {u.unit_id: 'invalid_or_truncated_response' for u in batch}
                # Item checkpoint and its completion membership change together.
                with store.transaction():
                    for unit in batch:
                        if unit.unit_id in good and unit.unit_id not in completed:
                            accept(unit, good[unit.unit_id], record_id)
                            completed.add(unit.unit_id)
                    store.execute('UPDATE ai_analysis_requests SET status=?,details=? WHERE batch_id=?',
                        ['completed' if not errors else 'partial', json.dumps({'completed': list(good), 'errors': errors}), active['batch_id']])
                if errors:
                    clean_streak = 0
                    width = next_batch_width(width, clean_streak=0, outcome='size_failure')
                    for unit in batch:
                        if unit.unit_id in errors:
                            repairs[unit.unit_id] = repairs.get(unit.unit_id, 0) + 1
                            if repairs[unit.unit_id] > 1:
                                fatal = ValueError('incomplete_ai_response')
                            else:
                                pending.append(((unit,), active['route'], 0, 0.))
                else:
                    clean_streak += 1
                    if execution.request.max_files_per_request is None and clean_streak >= 3:
                        width = next_batch_width(width, clean_streak=clean_streak, outcome='clean')
                        clean_streak = 0
                state('extracting')
            if fatal:
                pending.clear()
                if not inflight:
                    raise fatal
            while pending and len(inflight) < parallel and not fatal:
                index = next((i for i, item in enumerate(pending) if item[3] <= time.time()), None)
                if index is None:
                    break
                remaining, route_index, retry, _ = pending.pop(index)
                pid, configured = routes[route_index]
                profile = configured
                batch = pack_batch(remaining, contexts, execution, profile, width=width,
                                   privacy_chars=store.setting(workspace, 'max_context_chars', 8000))
                # A singleton uses the established smaller envelope, including on fallback.
                batch = batch or remaining[:1]
                local = copy(execution)
                local.catalog = contexts[batch[0].unit_id]
                if len(batch) == 1:
                    profile = project_profile(configured, batch[0])
                    system, user, prompt_hash = analysis_prompt(batch[0], 'project_lineage', local)
                else:
                    system, user = batch_prompt(batch, local, contexts)
                    prompt_hash = hashlib.sha256((system + user).encode()).hexdigest()
                if not request_allowance(profile, system, user, privacy_chars=store.setting(workspace, 'max_context_chars', 8000)).valid:
                    if route_index + 1 < len(routes):
                        pending.append((remaining, route_index + 1, 0, 0.))
                        continue
                    fatal = ValueError('indivisible_prompt_exceeds_model_capacity')
                    break
                slot = request_slot(store.home, workspace, parallel)
                try:
                    slot.__enter__()
                except ValueError:
                    pending.insert(index, (remaining, route_index, retry, time.time() + .1))
                    break
                batch_id = uuid.uuid4().hex
                save_request(store, workspace, run_id, batch_id, [u.unit_id for u in batch])
                bound = manager.for_profile(pid, configured) if hasattr(manager, 'for_profile') else manager
                sent_user = bound.redact(user) if store.setting(workspace, 'redact_secrets', True) else user
                message = AdmissionMessage(stop=stop)
                future = pool.submit(dispatch_provider_request, WorkerRequest(profile, system, sent_user,
                    bound, execution.transport, execution.cancelled), admissions, message)
                inflight[future] = {'message': message, 'batch_id': batch_id, 'units': batch,
                    'profile': profile, 'route': route_index, 'retry': retry, 'slot': slot,
                    'prompt_hash': prompt_hash, 'prompt_version': '5-batch1' if len(batch) > 1 else PROJECT_PROTOCOLS['project_lineage'][1],
                    'started': time.monotonic(), 'user': user,
                    'estimated_input': estimate_tokens(system, user).upper_bound}
                if len(batch) < len(remaining):
                    pending.insert(0, (remaining[len(batch):], route_index, 0, 0.))
            if pending or inflight:
                before = execution.clock()
                time.sleep(.01)
                # Quota delay is elapsed wall time, not active provider execution time.
                if not any(v['message'].ticket for v in inflight.values()):
                    execution.started += execution.clock() - before
        if unknown:
            raise TimeoutError('unknown_inflight_request_requires_explicit_retry')
