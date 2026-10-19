"""Explicit AI build controls, offline preview and persisted worker progress."""
from pathlib import Path

import streamlit as st

from dataforge.agent.jobs import TERMINAL, Jobs
from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.analysis_service import analysis_report, preview_analysis, run_analysis
from dataforge.connections import current_connections


@st.cache_resource(max_entries=8)
def analysis_jobs(home):
    return Jobs(Path(home))


def controls(store, workspace, file_ids):
    if not st.checkbox('Use AI for analysis', key='ai_build_' + workspace):
        return None, True
    compare = st.checkbox('Compare with parser', value=True, key='ai_compare_' + workspace)
    review = st.checkbox('Additional AI review', key='ai_review_' + workspace)
    if not compare:
        st.warning('AI-generated mode is experimental. Unsupported claims remain unresolved; parser-only relationships are omitted.')
    with st.expander('AI request budget'):
        attempts = st.number_input('Maximum provider attempts', 1, 2000, 200, key='ai_attempts_' + workspace)
        tokens = st.number_input('Maximum reserved output tokens', 1000, 2000000, 200000, step=1000,
                                key='ai_output_' + workspace)
        seconds = st.number_input('Execution time budget (seconds)', 30, 14400, 1800,
                                  key='ai_seconds_' + workspace)
        refresh = st.checkbox('Refresh saved AI extraction', key='ai_refresh_' + workspace)
        st.caption('Retries, fallback requests and optional review count toward the budget. Cancellation and deadlines are cooperative; an in-flight request may already be billed.')
    request = AnalysisRequest(mode='hybrid' if compare else 'ai', file_ids=file_ids,
        additional_ai_review=review, max_provider_attempts=attempts,
        max_output_tokens_total=tokens, max_seconds=seconds, refresh_ai=refresh)
    try:
        preview = preview_analysis(store, workspace, request, connections=current_connections())
        st.caption(f"{preview['files']} selected files · {preview['units']} complete source units · "
                   f"at most {preview['max_provider_attempts']} provider attempts including retries and fallback.")
        if preview['routes']:
            st.dataframe([{'Task': task, 'Provider': p['provider'], 'Model': p['model']}
                          for task, profiles in preview['routes'].items() for p in profiles],
                         hide_index=True, alt='Configured AI routes for this build')
        st.caption('Selected SQL/SAS source and relevant declarations are sent to these routes. A local gateway such as OmniRoute may forward requests. AI additions remain inferred.')
        if preview['blocked']:
            reasons = sorted({b['reason'] for b in preview['blocked']})
            st.warning('AI build needs attention: ' + '; '.join(reasons))
            st.caption('For context limits, adjust both Connections & AI → Privacy → context budget and the provider profile context size. Complete remote files require the full-source permission. Large indivisible units also need a larger chunk size in Workspace settings.')
        with st.expander('Source disclosure preview', on_change='rerun', key='ai_disclosure_' + workspace) as panel:
            if panel.open:
                st.dataframe(preview['disclosure'], hide_index=True, alt='Selected source files and immutable hashes to be disclosed')
        return request, preview['valid']
    except ValueError as exc:
        st.warning(str(exc))
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
    if record['status'] not in TERMINAL:
        if st.button('Cancel AI analysis', key='ai_cancel_' + workspace):
            jobs.cancel(job_id, workspace)
            st.info('Cancellation requested. The last committed lineage stays available.')
        return
    result = record.get('result', {})
    if result.get('status') == 'committed':
        st.success('AI analysis committed. Open lineage or inspect the validation report below.')
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
    counts = summary.get('counts', {})
    st.write(f"Requests: {counts.get('requests', 0)} · cached units: {counts.get('cache_hits', 0)} · "
             f"accepted: {counts.get('accepted', 0)} · rejected: {counts.get('rejected', 0)} · "
             f"unresolved: {counts.get('unresolved', 0)}")
    st.caption(f"Reported tokens: {counts.get('input_tokens', 0)} input / {counts.get('output_tokens', 0)} output"
               if summary.get('usage_known') else 'Provider token usage is unknown or only partially reported. Cached reuse makes no new extraction request.')
    st.caption(f"Agreed: {counts.get('agreed', 0)} · parser only: {counts.get('parser_only', 0)} · "
               f"AI only: {counts.get('ai_only', 0)} · units with coverage gaps: {counts.get('coverage_gaps', 0)}")
    if summary.get('reasons'):
        st.warning('; '.join(summary['reasons']))
    st.dataframe([{'Claim': c['claim_id'], 'Kind': c['kind'], 'Outcome': c['status'],
                   'Reasons': ', '.join(c['reasons'])} for c in result['claims']],
                 hide_index=True, alt='Source validation outcomes for AI candidates')
    with st.expander('Inspect exact candidate evidence', on_change='rerun', key='ai_claims_' + workspace) as panel:
        if panel.open:
            st.json(result['claims'])
