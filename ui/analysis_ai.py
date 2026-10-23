"""Explicit AI build controls, offline preview and persisted worker progress."""
from datetime import timedelta
from pathlib import Path
from time import monotonic, time

import streamlit as st

from dataforge.agent.jobs import TERMINAL, Jobs
from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.analysis_service import analysis_report, preview_analysis, recovery_message, run_analysis
from dataforge.connections import current_connections


@st.cache_resource(max_entries=8)
def analysis_jobs(home):
    return Jobs(Path(home))


def _preview_with_status(store, workspace, request, status, activity, started):
    """Show actual local preparation work; the native timer ticks between callbacks."""
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
    status.update(label=('Needs attention' if blocked else 'Ready') + ' · Elapsed: ' +
                  str(timedelta(seconds=int(monotonic() - started))),
                  state='error' if blocked else 'complete', expanded=blocked)
    return preview


def controls(store, workspace, file_ids):
    if not st.checkbox('Use AI for analysis', key='ai_build_' + workspace):
        return None, True
    st.caption('AI extracts actual file contents independently. Every fact remains inferred; semantic completeness is not proven.')
    with st.expander('AI spending limit'):
        ceiling = st.number_input('Run output token ceiling (optional)', min_value=1000, max_value=2000000,
            value=None, key='ai_run_output_' + workspace,
            help='Reserved output across every physical attempt, including retries and resumes. Leave blank for no run ceiling.')
    request = AnalysisRequest(mode='ai', file_ids=file_ids, max_output_tokens_total=ceiling)
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


@st.fragment(run_every=2)
def progress(store, workspace):
    job_id = st.session_state.get('ai_analysis_job_' + workspace)
    if not job_id:
        return
    jobs = analysis_jobs(str(store.home))
    record = jobs.read(job_id, workspace)
    st.progress(float(record['progress']), text=record.get('stage', record['status']))
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
        if st.button('Cancel AI analysis', key='ai_cancel_' + workspace):
            jobs.cancel(job_id, workspace)
            st.info('Cancellation requested. The last committed lineage stays available.')
        return
    result = record.get('result', {})
    if result.get('status') == 'committed':
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
    result = analysis_report(store, workspace, selected, include_source=True)
    summary = result['summary']
    if result['status'] in {'awaiting_continuation', 'interrupted', 'cancelled', 'failed'} and 'request' in result['summary']:
        from dataforge.ai_pipeline_store import recover_pipeline
        unknown = bool(result['summary'].get('inflight') or recover_pipeline(store, workspace, selected)['unknown'])
        exhausted = summary.get('last_failure', {}).get('allowance_exhausted') or 'batch_retry_allowance_exhausted' in summary.get('reasons', [])
        needs_ack = exhausted or (unknown and not summary.get('retry_policy', {}).get('unknown_retries', 0))
        retry = st.checkbox('Retry the unfinished batch (may incur a duplicate charge; renews the bounded retry allowance)', key='ai_retry_' + selected) if needs_ack else False
        if summary.get('protocol_version') != 5:
            st.info('This historical run uses an incompatible protocol. Start a new build.')
        elif st.button('Continue AI analysis', disabled=needs_ack and not retry):
            request = AnalysisRequest.model_validate({**summary['request'], 'resume_run_id': selected, 'retry_unknown': retry})
            start(store, workspace, request)
            st.rerun()

    counts = summary.get('counts', {})
    st.write(f"Requests: {counts.get('requests', 0)} · reused parts: {counts.get('cache_hits', 0)} · "
             f"accepted: {counts.get('accepted', 0)} · rejected: {counts.get('rejected', 0)} · "
             f"unresolved: {counts.get('unresolved', 0)}")
    st.caption(f"Reported tokens: {counts.get('input_tokens', 0)} input / {counts.get('output_tokens', 0)} output"
               if summary.get('usage_known') else 'Provider token usage is unknown or only partially reported. Cached reuse makes no new extraction request.')
    st.caption(f"Processed parts: {counts.get('processed', 0)} · Files: {counts.get('files', 0)} · "
               f"Incomplete coverage: {counts.get('coverage_gaps', 0)} · Stage: {summary.get('stage', result['status'])}")
    if summary.get('reasons'):
        st.warning(recovery_message(summary))
    if summary.get('last_failure'):
        with st.expander('Connection diagnostics'):
            st.json(summary['last_failure'])
    st.dataframe([{'Claim': c['claim_id'], 'Kind': c['kind'], 'Outcome': c['status'],
                   'Reasons': ', '.join(c['reasons'])} for c in result['claims']],
                 hide_index=True, alt='Source validation outcomes for AI candidates')
    with st.expander('Inspect exact candidate evidence', on_change='rerun', key='ai_claims_' + workspace) as panel:
        if panel.open:
            st.json(result['claims'])
