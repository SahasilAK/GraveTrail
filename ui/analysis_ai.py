"""Explicit AI build controls, offline preview and persisted worker progress."""
from datetime import timedelta
from pathlib import Path
from time import monotonic, time

import streamlit as st

from dataforge.agent.jobs import TERMINAL, Jobs
from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.analysis_service import analysis_report, preview_analysis, run_analysis
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
    max_files = st.number_input('Maximum files per request', 1, 100, value=None,
        placeholder='Auto', key='ai_files_per_request_' + workspace,
        help='An upper bound. Context size, output space and the 8-item safety cap may reduce a request.')
    max_parallel = st.number_input('Maximum parallel requests', 1, 4, value=None,
        placeholder='Auto', key='ai_parallel_requests_' + workspace,
        help='Further limited by workspace concurrency, shared provider quotas and available request slots.')
    compare = st.checkbox('Compare with parser', value=True, key='ai_compare_' + workspace)
    review = st.checkbox('Additional AI review', key='ai_review_' + workspace)
    if not compare:
        st.warning('AI-generated mode is experimental. Unsupported claims remain unresolved; parser-only relationships are omitted.')
    refresh = st.checkbox('Refresh saved AI extraction', key='ai_refresh_' + workspace)
    base = dict(mode='hybrid' if compare else 'ai', file_ids=file_ids,
                additional_ai_review=review, refresh_ai=refresh,
                max_files_per_request=max_files, max_parallel_requests=max_parallel,
                max_context_chars=st.session_state.get('ai_context_chars_' + workspace))
    status = st.status('Preparing AI analysis…', expanded=False)
    status.caption('Local preparation only. Model requests start when you choose Analyze.')
    activity = status.empty()
    started = monotonic()
    try:
        automatic = _preview_with_status(store, workspace, AnalysisRequest(**base), status, activity, started)
    except ValueError as exc:
        status.warning(str(exc))
        return AnalysisRequest(**base), False
    except Exception:
        status.error('Could not prepare AI analysis. Try again or review your source selection and provider settings.')
        return AnalysisRequest(**base), False
    overrides = {}
    with st.expander('AI request budget'):
        base['auto_continue'] = st.checkbox('Automatically continue execution windows', value=True,
            key='ai_auto_continue_' + workspace)
        def reset():
            st.session_state.pop('ai_context_chars_' + workspace, None)
            for suffix in ('attempts', 'output', 'seconds'):
                st.session_state.pop('ai_custom_' + suffix + '_' + workspace, None)
                st.session_state.pop('ai_custom_value_' + suffix + '_' + workspace, None)
            st.session_state['ai_budget_reset_' + workspace] = True
        st.button('Reset AI budgets to automatic', on_click=reset)
        base['max_context_chars'] = st.number_input('Maximum source/context characters per request',
            500, 2000000, value=None, placeholder='Auto', key='ai_context_chars_' + workspace,
            help='Optional for this build. Replaces saved workspace/profile character allowances; '
                 'model token limits and source permissions still apply. Auto splits work to fit.')
        st.caption('Character allowances cover disclosed source and project context. Instructions, response schema '
                   'and reserved output are checked separately against model capacity; you do not need to calculate them.')
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
        st.caption('These are per-execution limits. Larger builds continue automatically within the finite project allowance below. In-flight requests may already be billed.')
        for field, label, low, high in [
            ('project_max_provider_attempts', 'Project maximum provider attempts', 1, 100000000),
            ('project_max_output_tokens_total', 'Project maximum reserved output tokens', 1000, 1000000000000),
            ('project_max_seconds', 'Project maximum active seconds', 30, 31536000)]:
            base[field] = st.number_input(label, low, high, value=None, placeholder='Auto', key=field + '_' + workspace)
    request = AnalysisRequest(**base, **overrides)
    try:
        preview = (_preview_with_status(store, workspace, request, status, activity, started)
                   if any(value is not None for value in overrides.values()) or any(base.get(k) is not None
                       for k in ('project_max_provider_attempts', 'project_max_output_tokens_total', 'project_max_seconds')) else automatic)
        st.caption(f"{preview['files']} selected files · {preview['units']} source tasks · "
                   f"at most {preview['max_provider_attempts']} provider attempts including retries and fallback.")
        allowance = preview.get('project_allowance', {})
        if allowance:
            st.caption(f"Project lifetime allowance: {allowance['max_provider_attempts']:,} attempts · "
                       f"{allowance['max_output_tokens_total']:,} reserved output tokens. "
                       'Includes bounded repair and resolution work; reservation is not billed usage.')
        if preview.get('semantic_pages'):
            st.caption(f"{preview['semantic_pages']} projection tasks retain original shared SQL context and validate against the complete source.")
        if preview.get('source_context_pages'):
            st.caption(f"{preview['source_context_pages']} bounded source/context views will be checkpointed and combined. "
                       'Original evidence is preserved; unsupported or incomplete semantics remain explicit.')
        if preview.get('review_sizing_provisional'):
            st.caption('Review sizing is provisional until extraction produces candidates. Additional batches continue within the saved execution limits; completed batches are reused.')
        if preview['routes']:
            st.dataframe([{'Task': task, 'Provider': p['provider'], 'Model': p['model']}
                          for task, profiles in preview['routes'].items() for p in profiles],
                         hide_index=True, alt='Configured AI routes for this build')
        st.caption('Selected SQL/SAS/dbt source and disclosed project context are sent to these routes. A local gateway such as OmniRoute may forward requests. AI additions remain inferred. Provider rate limits are learned separately from model context size.')
        if preview.get('excluded_routes'):
            names = {p['profile_id']: p['name'] for p in store.rows(
                'SELECT profile_id,name FROM llm_profiles WHERE workspace_id=?', [workspace])}
            excluded = sorted({(names.get(p['profile_id'], p['profile_id']), p['reason'].replace('_', ' '))
                               for p in preview['excluded_routes']})
            st.caption('Skipped fallback profiles: ' + '; '.join(name + ': ' + reason for name, reason in excluded))

        if preview.get('remaining_units'):
            st.info(f"This window covers up to {preview['selected_new_units']} units needing AI work; "
                    f"{preview['remaining_units']} continue {'automatically' if request.auto_continue else 'when resumed'}. "
                    'The current graph remains until all required units finish.')
        st.caption('Input estimates use conservative UTF-8 bytes plus framing and capacity headroom; reported usage is shown after execution.')
        if preview['blocked']:
            reasons = sorted({b['reason'] for b in preview['blocked']})
            status.warning('; '.join(r.replace('_', ' ') for r in reasons))
            st.warning('AI build needs attention: ' + '; '.join(r.replace('_', ' ') for r in reasons))
            st.caption('Requests adapt to source size and model capacity using complete statements, projection groups or exact source/context views. Saved components are combined and validated against the original before lineage is published.')
        with st.expander('Source files and request sizes', expanded=False, on_change='rerun',
                         key='ai_sizes_' + workspace) as sizes:
            if sizes.open:
                from dataforge.ai_budget import file_sizing
                st.caption('Click any column heading to sort ascending or descending. Request characters include '
                           'instructions and schema; the character allowance applies to source/context only. '
                           'Blank model token allowances mean capacity is unknown. Values describe planned single-task requests.')
                st.dataframe(file_sizing(preview), hide_index=True, alt='Source files, planned request sizes, allowances and blockers')
        with st.expander('Source disclosure preview', on_change='rerun', key='ai_disclosure_' + workspace) as panel:
            if panel.open:
                st.dataframe(preview['disclosure'], hide_index=True, alt='Selected source files and immutable hashes to be disclosed')
        return request, preview['valid']
    except ValueError as exc:
        status.warning(str(exc))
        return request, False
    except Exception:
        status.error('Could not prepare AI analysis. Try again or review your source selection and provider settings.')
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
        from dataforge.ai_pipeline_store import recover_pipeline
        unknown = bool(result['summary'].get('inflight') or recover_pipeline(store, workspace, selected)['unknown'])
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
