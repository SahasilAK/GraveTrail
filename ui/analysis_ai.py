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
    refresh = st.checkbox('Refresh saved AI extraction', key='ai_refresh_' + workspace)
    base = dict(mode='hybrid' if compare else 'ai', file_ids=file_ids,
                additional_ai_review=review, refresh_ai=refresh)
    try:
        automatic = preview_analysis(store, workspace, AnalysisRequest(**base), connections=current_connections())
    except ValueError as exc:
        st.warning(str(exc))
        return AnalysisRequest(**base), False
    overrides = {}
    with st.expander('AI request budget'):
        def reset():
            for suffix in ('attempts', 'output', 'seconds'):
                st.session_state.pop('ai_custom_' + suffix + '_' + workspace, None)
                st.session_state.pop('ai_custom_value_' + suffix + '_' + workspace, None)
            st.session_state['ai_budget_reset_' + workspace] = True
        st.button('Reset AI budgets to automatic', on_click=reset)
        fields = [('attempts', 'max_provider_attempts', 'Maximum provider attempts', 1, 2000, 1),
                  ('output', 'max_output_tokens_total', 'Maximum reserved output tokens', 1000, 2000000, 1000),
                  ('seconds', 'max_seconds', 'Execution time budget (seconds)', 30, 14400, 1)]
        for suffix, field, label, low, high, step in fields:
            key = 'ai_' + suffix + '_' + workspace
            custom_key = 'ai_custom_' + suffix + '_' + workspace
            value_key = 'ai_custom_value_' + suffix + '_' + workspace
            custom = st.session_state.get(custom_key, False)
            if custom:
                st.session_state[key] = st.session_state.get(value_key, st.session_state.get(key, low))
            else:
                st.session_state[key] = automatic['recommended'][field]
            def edited(custom_key=custom_key, value_key=value_key, key=key):
                st.session_state[custom_key] = True
                st.session_state[value_key] = st.session_state[key]
            value = st.number_input(label, low, high, step=step, key=key, on_change=edited)
            overrides[field] = value if custom else None
            st.caption(label + ': ' + ('Custom' if custom else 'Automatic'))
        st.caption('Automatic values include retries, fallback and optional review. Each execution stays within application limits; larger projects continue explicitly. In-flight requests may already be billed.')
    request = AnalysisRequest(**base, **overrides)
    try:
        preview = preview_analysis(store, workspace, request, connections=current_connections())
        st.caption(f"{preview['files']} selected files · {preview['units']} complete source units · "
                   f"at most {preview['max_provider_attempts']} provider attempts including retries and fallback.")
        if preview['routes']:
            st.dataframe([{'Task': task, 'Provider': p['provider'], 'Model': p['model']}
                          for task, profiles in preview['routes'].items() for p in profiles],
                         hide_index=True, alt='Configured AI routes for this build')
        st.caption('Selected SQL/SAS source and relevant declarations are sent to these routes. A local gateway such as OmniRoute may forward requests. AI additions remain inferred.')
        if preview.get('excluded_routes'):
            names = {p['profile_id']: p['name'] for p in store.rows(
                'SELECT profile_id,name FROM llm_profiles WHERE workspace_id=?', [workspace])}
            excluded = sorted({(names.get(p['profile_id'], p['profile_id']), p['reason'].replace('_', ' '))
                               for p in preview['excluded_routes']})
            st.caption('Skipped fallback profiles: ' + '; '.join(name + ': ' + reason for name, reason in excluded))

        if preview.get('remaining_units'):
            st.info(f"This execution covers {preview['selected_new_units']} units needing AI work; {preview['remaining_units']} continue later. The current graph remains until all units finish.")
        st.caption('Input estimates use conservative UTF-8 bytes plus framing and capacity headroom; reported usage is shown after execution.')
        if preview['blocked']:
            reasons = sorted({b['reason'] for b in preview['blocked']})
            st.warning('AI build needs attention: ' + '; '.join(r.replace('_', ' ') for r in reasons))
            st.caption('Whole SQL/SAS blocks are preserved. Model capacity, source disclosure allowance and execution limits are checked separately.')
            affected = {b.get('unit_id') for b in preview['blocked'] if b.get('unit_id')}
            if affected:
                paths = {a['path'] for a in preview.get('allowances', []) if a['unit_id'] in affected}
                st.caption('Affected source selection: ' + ', '.join(sorted(paths)))
            required = max((a['required_characters'] for a in preview.get('allowances', []) if not a['valid']), default=0)
            if 'complete_prompt_exceeds_context_budget' in reasons and 0 < required <= 100000:
                if st.button(f'Apply calculated context allowance ({required:,} characters)'):
                    from dataforge.analysis_service import apply_context_allowance
                    from dataforge.settings_service import revision
                    apply_context_allowance(store, workspace, request, required, revision(store, workspace))
                    st.rerun()
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
    elif result.get('status') == 'awaiting_continuation':
        st.info('Analysis paused with saved progress. Continue below; the current graph remains available.')
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
        unknown = bool(result['summary'].get('inflight'))
        retry = st.checkbox('Retry the unknown in-flight request (may incur a duplicate charge)', key='ai_retry_' + selected) if unknown else False
        limits = {}
        for suffix, field in [('attempts', 'max_provider_attempts'), ('output', 'max_output_tokens_total'), ('seconds', 'max_seconds')]:
            if st.session_state.get('ai_custom_' + suffix + '_' + workspace):
                limits[field] = st.session_state.get('ai_custom_value_' + suffix + '_' + workspace,
                    summary['request'].get(field))
            elif st.session_state.get('ai_budget_reset_' + workspace):
                limits[field] = None
            else:
                limits[field] = summary['request'].get(field)
        st.caption('Continue preserves saved Custom ceilings. Edit the AI request budget or Reset to automatic to change them.')
        if st.button('Continue AI analysis', disabled=unknown and not retry):
            request = AnalysisRequest.model_validate({**summary['request'], 'resume_run_id': selected,
                                                     'retry_unknown': retry, **limits})
            start(store, workspace, request)
            st.rerun()

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
