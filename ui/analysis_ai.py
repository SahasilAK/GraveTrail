"""Explicit AI build controls, offline preview and persisted worker progress."""
from datetime import timedelta
from pathlib import Path
from time import monotonic, time

import streamlit as st

from dataforge.agent.jobs import TERMINAL, Jobs
from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_analysis_progress import analysis_progress
from dataforge.ai_budget import allocate_analysis_profile
from dataforge.ai_context import inventory_revision
from dataforge.analysis_service import analysis_report, preview_analysis, recovery_message, run_analysis
from dataforge.connections import current_connections
from dataforge.llm import analysis_routes
from dataforge.settings_service import revision


@st.cache_resource(max_entries=8)
def analysis_jobs(home):
    return Jobs(Path(home))


def _preview_with_status(store, workspace, request, status, activity, started):
    """Show actual local preparation work; the native timer ticks between callbacks."""
    cache_key = None
    try:
        pid, profile = analysis_routes(store, workspace, 'project_lineage')[0]
        allocate_analysis_profile(profile, request)  # Expired metadata cannot reuse a ready preview.
        manager = current_connections()
        bound = manager.for_profile(pid, profile) if hasattr(manager, 'for_profile') else manager
        cache_key = (str(store.home), request.model_dump_json(), inventory_revision(store, workspace),
                     revision(store, workspace), profile.model_dump_json(), bool(not profile.key_env or bound.resolve(profile.key_env)))
    except ValueError:
        pass
    cached = st.session_state.get('ai_preview_' + workspace)
    if cache_key is not None and cached and cached['key'] == cache_key:
        status.update(label='Ready · Reusing unchanged offline preview', state='complete')
        return cached['preview']
    stages = {}
    last_update = 0

    def update(stage, completed, total):
        nonlocal last_update
        now = monotonic()
        changed = stage not in stages
        stages[stage] = f'{completed:,} / {total:,}'
        if changed or completed == total or now - last_update >= .1:
            status.update(label=stage + '…', state='running')
            activity.markdown('\n'.join(f'- {name} — {count}' for name, count in stages.items()))
            last_update = now

    status.update(label='Preparing AI analysis…', state='running')
    try:
        with st.spinner('Preparing AI analysis…', show_time=True):
            preview = preview_analysis(store, workspace, request, connections=current_connections(), progress=update)
    except Exception:
        status.update(label='Preparation failed · Elapsed: ' + str(timedelta(seconds=int(monotonic() - started))),
                      state='error', expanded=True)
        raise
    blocked = not preview['valid']
    if not blocked and cache_key is not None:
        st.session_state['ai_preview_' + workspace] = {'key': cache_key, 'preview': preview}
    status.update(label=('Needs attention' if blocked else 'Ready') + ' · Elapsed: ' +
                  str(timedelta(seconds=int(monotonic() - started))),
                  state='error' if blocked else 'complete', expanded=blocked)
    return preview


def controls(store, workspace, file_ids):
    if not st.checkbox('Use AI for analysis', key='ai_build_' + workspace, persist_state='session'):
        return None, True
    st.caption('AI extracts actual file contents independently. Every fact remains inferred; semantic completeness is not proven.')
    with st.expander('AI spending limit'):
        ceiling = st.number_input('Run output token ceiling (optional)', min_value=1000, max_value=2000000,
            value=None, key='ai_run_output_' + workspace, persist_state='session',
            help='Reserved output across every physical attempt, including retries and resumes. Leave blank for no run ceiling.')
    with st.expander('AI budget overrides'):
        share = st.slider('Maximum output share (%)', 10, 50, 30, key='ai_output_share_' + workspace, persist_state='session',
            on_change=lambda: st.session_state.update({'ai_slider_override_' + workspace: True}),
            help='A maximum output allowance, not a request to generate that many tokens. Shared windows divide usable context; separate windows use a fraction of output capacity.')
        input_override, output_override = None, None
        with st.expander('Advanced token overrides'):
            override = st.checkbox('Override per-request token allowances', key='ai_exact_override_' + workspace, persist_state='session')
            st.caption('Moving the slider explicitly selects this run’s allowance instead of the saved Custom default. Exact overrides take precedence. Model limits always apply; saved profiles are not changed.')
            if override:
                input_override = st.number_input('Effective input tokens (optional)', min_value=1, max_value=2147483647,
                    value=None, key='ai_exact_input_' + workspace, persist_state='session')
                output_override = st.number_input('Maximum output tokens per request (optional)', min_value=64, max_value=2147483647,
                    value=None, key='ai_exact_output_' + workspace, persist_state='session')
        request = AnalysisRequest(mode='ai', file_ids=file_ids, max_output_tokens_total=ceiling,
            output_share=share, input_token_limit=input_override, output_token_limit=output_override)
        try:
            profile = analysis_routes(store, workspace, 'project_lineage')[0][1]
            slider_clamps = []
            if output_override is None and st.session_state.get('ai_slider_override_' + workspace):
                slider_profile, slider_allocation = allocate_analysis_profile(profile.model_copy(update={'output_mode': 'automatic'}), request)
                slider_clamps = slider_allocation['clamps']
                request = request.model_copy(update={'output_token_limit': slider_profile.max_tokens})
            _, allocation = allocate_analysis_profile(profile, request)
            st.metric('Effective input allowance (tokens)', f"{allocation['input_allowance']:,}")
            st.metric('Maximum output allowance per request (tokens)', f"{allocation['output_allowance']:,}")
            st.caption(f"Model/route capacity: context {allocation['context_capacity'] or 'unreported'}, "
                f"input {allocation['input_capacity'] or 'unreported'}, output {allocation['output_capacity'] or 'unreported'}. "
                f"Source: {allocation['source']}; windows: {allocation['window']}. "
                + ('Dynamic route: manually confirmed limits apply.' if allocation['dynamic'] else ''))
            explanations = {'saved_custom_output_limit': 'The saved Custom output allowance is the current default; move the slider or use Advanced to change this run.',
                'model_output_limit': 'The model output limit clamps the requested allowance. Effective values will stay fixed above this limit.',
                'model_input_limit': 'The model input limit clamps the available input.',
                'shared_context_limit': 'The shared context window clamps the requested output.',
                'available_input_limit': 'The available model input allowance clamps the exact input override.'}
            for reason in dict.fromkeys(allocation['clamps'] + slider_clamps):
                st.caption(explanations[reason])
            for note in allocation['notes']:
                st.caption(note)
        except ValueError:
            st.caption('Effective allowances need confirmed model limits. Dynamic routes require a route-safe manual capacity override in provider settings.')
    status = st.status('Preparing AI analysis…', expanded=False)
    status.caption('Offline preparation. Model requests start when you choose Analyze.')
    try:
        preview = _preview_with_status(store, workspace, request, status, status.empty(), monotonic())
        if not preview['valid']:
            st.warning('AI build needs attention: ' + '; '.join(b['reason'].replace('_', ' ') for b in preview['blocked']))
            return request, False
        st.write(f"Family: {preview['source_kind']} · Files: {preview['files']} · Parts: {preview['parts']} · Estimated requests: {preview['estimated_requests']}")
        st.caption(f"Estimated tokens: {preview['estimated_input_tokens']:,} input / {preview['estimated_output_tokens']:,} reserved output. "
                   f"Counting: {preview['estimate_method']}. Completion and consolidation may require additional requests.")
        for profiles in preview['routes'].values():
            for profile in profiles:
                st.caption(profile['provider'] + ' · ' + profile['model'])
        st.json(preview['limits'], expanded=False)
        with st.expander('Request budget estimates'):
            st.caption('Output allowance is configured per request. Advertised model capacity may vary with gateway routing. '
                       'Packing reports eligible work, input utilization, expected output and any limiting budget.')
            st.json(preview.get('packing', []), expanded=False)
        with st.expander('Source disclosure preview'):
            st.dataframe(preview['disclosure'], hide_index=True, alt='Pinned selected sources and hashes')
        return request, True
    except ValueError as exc:
        status.warning(str(exc))
        return request, False
    except Exception:
        status.error('Could not prepare AI analysis. Review source selection and provider settings.')
        return request, False


def start(store, workspace, request):
    manager = current_connections()
    job = analysis_jobs(str(store.home)).start(workspace, 'ai_analysis',
        lambda progress, cancelled: run_analysis(store, workspace, request, connections=manager,
            progress=progress, cancelled=cancelled).model_dump(), connections=manager, cancellable=True)
    st.session_state['ai_analysis_job_' + workspace] = job['job_id']


def render_status(snapshot):
    """Use identical ledger definitions for running and saved analysis."""
    st.write(f"Run: {snapshot['run_id']} · Status: {snapshot['status']} · Stage: {snapshot['stage']}")
    for group, prefix in [('files', 'Files'), ('parts', 'Parts')]:
        with st.container(horizontal=True):
            for name, value in snapshot[group].items():
                st.metric(f'{prefix} {name}', 'Unknown' if value is None else str(value), border=True)
    for group in ('requests', 'attempts'):
        st.write(group.title() + ': ' + ' · '.join(f'{key.replace("_", " ")}: {value}' for key, value in snapshot[group].items()))
    st.caption(f"Pending recovery parts: {snapshot['recovery_pending']}. Failed attempts do not mean failed files. Reused parts are saved successes, not skipped work.")
    tokens = snapshot['tokens']
    def value(key):
        return 'Unknown' if tokens[key] is None else f'{tokens[key]:,}'
    st.caption(f"Initial estimated input tokens: {value('estimated_input')} · Reserved output across attempts: {value('reserved_output')}")
    st.caption(f"Provider-reported tokens: {value('actual_input')} input / {value('actual_output')} output. "
               f"Known subtotals: {tokens['reported_input']:,} input / {tokens['reported_output']:,} output; unknown attempts are excluded from these subtotals.")
    estimate = snapshot.get('initial_estimate') or {}
    st.caption(f"Initial estimated requests: {estimate.get('requests', 'Unknown')}. Completion, consolidation and recovery may add work; totals can grow. No provider-internal progress is available while waiting.")
    for name, stage in snapshot['stages'].items():
        st.progress(stage['completed'] / max(1, stage['planned']),
            text=f"{name.replace('_', ' ').title()}: {stage['completed']} / {stage['planned']} saved parts")
    if snapshot['current']:
        st.write('Current request / attempt')
        st.json(snapshot['current'], expanded=False)
    if snapshot['activity']:
        with st.expander('Recent activity'):
            st.dataframe(snapshot['activity'], hide_index=True, alt='Recent bounded analysis activity')
    with st.expander('Counter definitions'):
        st.caption('Files completed have finalized processed extraction records. Partial files have saved work but are not completed; unfinished files have none. '
            'Parts planned include extraction, completion and consolidation, excluding superseded split parents. Completed parts have valid saved checkpoints; remaining includes unresolved work. '
            'Queued requests are durable planned batches without an in-flight attempt; future batches are not yet requests. Received attempts may still fail validation. '
            'Unknown attempts may have reached the provider. Output reservation is an allowance, not actual usage. Processing completion does not prove semantic completeness.')


@st.fragment(run_every=2)
def progress(store, workspace):
    job_id = st.session_state.get('ai_analysis_job_' + workspace)
    if not job_id:
        return
    jobs = analysis_jobs(str(store.home))
    record = jobs.read(job_id, workspace)
    if not record.get('run_id') or record['status'] in TERMINAL:
        st.progress(float(record['progress']), text=record.get('stage', record['status']))
    else:
        st.write(record.get('stage', record['status']))
    started = record.get('started_at')
    if started is not None:
        ended = record.get('finished_at', record.get('updated_at', started)) if record['status'] in TERMINAL else time()
        timing = f'Elapsed: {timedelta(seconds=max(0, int(ended - started)))}'
        if record['status'] not in TERMINAL and record.get('stage', '').startswith('Waiting for AI'):
            waiting = max(0, int(ended - record.get('stage_started_at', started)))
            timing += f' · Waiting: {timedelta(seconds=waiting)} · Waiting for provider response; refreshes every 2 seconds.'
        st.caption(timing)
    elif record['status'] == 'queued':
        st.caption('Queued — waiting for an analysis worker.')
    if record['status'] not in TERMINAL:
        cancel_key = 'ai_cancel_pending_' + job_id
        if record.get('cancel_requested') or st.session_state.get(cancel_key):
            st.info('Cancellation requested. Waiting for the worker to acknowledge; saved work is retained.')
        if st.button('Cancel AI analysis', key='ai_cancel_' + workspace,
                     disabled=record.get('cancel_requested', False) or st.session_state.get(cancel_key, False)):
            jobs.cancel(job_id, workspace)
            st.session_state[cancel_key] = True
            st.info('Cancellation requested. The last committed lineage stays available.')
        if record.get('run_id'):
            try:
                render_status(analysis_progress(store, workspace, record['run_id']))
            except ValueError:
                st.caption('Preparing this run; durable work planning is not yet available.')
        return
    result = record.get('result', {})
    if result.get('status') == 'committed':
        if result.get('counts', {}).get('unresolved_parts'):
            st.warning('Available validated lineage published with incomplete coverage. Unresolved work can be retried from the report.')
        else:
            st.success('AI analysis committed. Open lineage or inspect the validation report below.')
    elif result.get('status') == 'awaiting_continuation':
        st.info(recovery_message(result))
    else:
        st.warning('AI analysis did not publish a new graph: ' + ', '.join(result.get('reasons', [record['status']])))
    if result.get('run_id'):
        st.session_state['ai_analysis_report_' + workspace] = result['run_id']
    refresh_key = 'ai_analysis_refreshed_' + workspace
    if st.session_state.get(refresh_key) != job_id:
        # A fragment refreshes only its own progress area. Refresh the outer
        # report/metrics once after publication so it cannot show staged counts.
        st.session_state[refresh_key] = job_id
        if result.get('run_id'):
            st.session_state['ai_report_choice_' + workspace] = result['run_id']
        st.rerun(scope='app')
    if st.button('Dismiss progress', key='ai_dismiss_' + workspace):
        st.session_state.pop('ai_analysis_job_' + workspace, None)
        st.rerun()


def report(store, workspace):
    run_id = st.session_state.get('ai_analysis_report_' + workspace)
    rows = store.rows('SELECT run_id,mode,status,created_at FROM ai_analysis_runs WHERE workspace_id=? ORDER BY created_at DESC LIMIT 50', [workspace])
    if not rows:
        return
    st.subheader('AI analysis and validation')
    choices = {r['run_id']: f"{r['created_at']} · {r['mode']} · {r['status']}" for r in rows}
    if run_id not in choices:
        run_id = next(iter(choices))
    selected = st.selectbox('AI analysis report', list(choices), index=list(choices).index(run_id),
                            format_func=choices.get, key='ai_report_choice_' + workspace)
    result = analysis_report(store, workspace, selected, include_source=False)
    summary = result['summary']
    if summary.get('protocol_version') == 5:
        render_status(analysis_progress(store, workspace, selected))
    partial_publication = result['status'] == 'committed' and bool(summary.get('unresolved_work'))
    if (result['status'] in {'awaiting_continuation', 'interrupted', 'cancelled', 'failed'} or partial_publication) and 'request' in summary:
        from dataforge.ai_pipeline_store import recover_pipeline
        unknown = bool(result['summary'].get('inflight') or recover_pipeline(store, workspace, selected)['unknown'])
        exhausted = not summary.get('recovery_queue') and (summary.get('last_failure', {}).get('allowance_exhausted') or
                                                         'batch_retry_allowance_exhausted' in summary.get('reasons', []))
        needs_ack = exhausted or (unknown and not summary.get('retry_policy', {}).get('unknown_retries', 0))
        retry = st.checkbox('Retry the unfinished batch (may incur a duplicate charge; renews the bounded retry allowance)', key='ai_retry_' + selected) if needs_ack else False
        if summary.get('protocol_version') != 5:
            st.info('This historical run uses an incompatible protocol. Start a new build.')
        elif st.button('Retry unresolved AI work' if partial_publication else 'Continue AI analysis', disabled=needs_ack and not retry):
            request = AnalysisRequest.model_validate({**summary['request'], 'budget_policy': summary['request'].get('budget_policy', 'legacy'),
                'resume_run_id': selected, 'retry_unknown': retry})
            start(store, workspace, request)
            st.rerun()

    counts = summary.get('counts', {})
    if summary.get('protocol_version') != 5:
        st.write(f"Requests: {counts.get('requests', 'Unknown')} · reused parts: {counts.get('cache_hits', 'Unknown')} · "
             f"accepted: {counts.get('accepted', 0)} · rejected: {counts.get('rejected', 0)} · "
             f"unresolved: {counts.get('unresolved', 0)}")
    st.caption(f"Extracted operations: {counts.get('accepted', 'Unknown')} · Unresolved semantic details: {counts.get('unresolved', 'Unknown')} · Incomplete coverage: {counts.get('coverage_gaps', 'Unknown')}")
    if summary.get('reasons'):
        st.warning(recovery_message(summary))
    if summary.get('last_failure'):
        with st.expander('Connection diagnostics'):
            st.json(summary['last_failure'])
    if summary.get('recovery_queue'):
        with st.expander('Pending extraction recovery'):
            st.caption('Unresolved work remains retryable after bounded recovery. Saved valid results are retained; published coverage stays incomplete.'
                if partial_publication else 'Required work remains pending. Recovery uses smaller batches and backoff; Cancel retains saved progress.')
            st.json(summary['recovery_queue'], expanded=False)
    if result.get('recent_requests'):
        with st.expander('Recent request and extraction diagnostics'):
            st.caption('Safe validation codes, field paths, recovery actions and request budgets. Raw responses are not retained.')
            st.json(result['recent_requests'], expanded=False)
    st.dataframe([{'Claim': c['claim_id'], 'Kind': c['kind'], 'Outcome': c['status'],
                   'Reasons': ', '.join(c['reasons'])} for c in result['claims']],
                 hide_index=True, alt='Source validation outcomes for AI candidates')
    with st.expander('Inspect exact candidate evidence', on_change='rerun', key='ai_claims_' + workspace) as panel:
        if panel.open:
            st.json(analysis_report(store, workspace, selected, include_source=True)['claims'])
