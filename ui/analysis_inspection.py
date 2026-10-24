"""Lazy request/attempt inspection shared by active and historical run views."""
import json

import streamlit as st

from dataforge.ai_inspection import MAX_ARTIFACT_BYTES, inspection_items, inspection_payload


def _artifact(store, workspace, run_id, ticket, kind, title, key):
    with st.expander(title, key=key, on_change='rerun') as panel:
        if not panel.open:
            return
        page = st.number_input('Content page (16,000 characters)', min_value=1, value=1, step=1,
                               key=key + '_page', persist_state='session')
        payload = inspection_payload(store, workspace, run_id, ticket, kind, offset=(page - 1) * 16000)
        st.caption(payload['status'] + (' · Redactions applied: [REDACTED]' if payload['redacted'] else ''))
        if payload['content'] is None:
            return
        st.caption(f"Page {page} · {payload['total_chars']:,} retained characters · " +
                   ('More pages available' if payload['has_more'] else 'End of retained content'))
        st.code(payload['content'], language=None)
        def download():
            result = inspection_payload(store, workspace, run_id, ticket, kind, limit=MAX_ARTIFACT_BYTES)
            return result['content'] if result['status'] == 'retained' else result['status']
        st.download_button('Download retained artifact', data=download,
            file_name=f'{run_id}-{ticket}-{kind}.txt', mime='text/plain', key=key + '_download', on_click='ignore')


def render_inspection(store, workspace, run_id):
    for section, kind in [('Inputs', 'input'), ('Outputs', 'output')]:
        key = f'ai_inspect_{workspace}_{run_id}_{kind}'
        with st.expander(section, key=key, on_change='rerun') as panel:
            if not panel.open:
                continue
            st.caption('Capture follows Workspace settings → Security and privacy → Store full AI interaction context locally. Retention is at most 7 days, 4 MiB per artifact and 64 MiB per run. Earlier or unretained content cannot be reconstructed.')
            page = st.number_input('Request/attempt page (20 per page)', min_value=1, value=1, step=1,
                                   key=key + '_page', persist_state='session')
            listing = inspection_items(store, workspace, run_id, offset=(page - 1) * 20)
            st.caption(f"{listing['total']} request/attempt items. Planned requests have no dispatched input yet. Historical uncaptured content: Not retained.")
            if not listing['items']:
                st.info('No request/attempt items on this page.')
                continue
            choices = {item['attempt_id'] or item['request_id']: item for item in listing['items']}
            def label(identity):
                item = choices[identity]
                return f"{item['work_kind'] or 'historical'} · {item['status']} · request {item['request_id']} · attempt {item['attempt_id'] or 'not dispatched'}"
            selected = st.selectbox('Request / attempt', list(choices), format_func=label,
                                    key=key + '_selection', persist_state='session')
            item = choices[selected]
            st.caption('Affected parts: ' + item['part_ids'])
            ticket = item['attempt_id']
            if ticket is None:
                st.info('Planned, not dispatched. No provider body or response exists for this request yet.')
                continue
            if kind == 'input':
                st.caption('Actual dispatched provider body: prompts, source/context, model parameters and output allowance. Headers are never retained.')
            else:
                st.caption('Captured provider response is separate from decoded/validated results. Pending or unknown outcomes may have no complete response. Content is displayed as data.')
                request = store.rows('SELECT details FROM ai_analysis_requests WHERE workspace_id=? AND run_id=? AND batch_id=?',
                    [workspace, run_id, item['request_id']])[0]
                st.json({'part_outcome': json.loads(request['details']).get('outcome', 'Validation outcome not checkpointed')}, expanded=False)
                details = store.rows('''SELECT status,details FROM ai_analysis_attempts
                    WHERE workspace_id=? AND run_id=? AND attempt_id=?''', [workspace, run_id, ticket])[0]
                st.json({'attempt_status': details['status'], 'diagnostics': json.loads(details['details'])}, expanded=False)
            _artifact(store, workspace, run_id, ticket, kind, 'Attempt ' + kind + ' · ' + ticket,
                      key + '_' + ticket)
            if kind == 'output':
                _artifact(store, workspace, run_id, ticket, 'decoded', 'Decoded results, validation errors and recovery · ' + ticket,
                          key + '_' + ticket + '_decoded')
