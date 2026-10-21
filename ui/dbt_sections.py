"""Native dbt project/resource panels over shared authorized report handlers."""
import streamlit as st

from dataforge.agent.contracts import QueryOptions
from dataforge.dbt.service import DbtOperations


def render_projects(store, workspace):
    projects = store.rows('SELECT * FROM dbt_projects WHERE workspace_id=? ORDER BY root_path', [workspace])
    if not projects:
        return
    import json
    with st.expander('dbt projects and coverage'):
        for project in projects:
            st.write(f"{project['package_name']} · {project['root_path']}")
            st.json(json.loads(project['coverage_json']), expanded=False)
        st.caption('Coverage describes static evidence. Imported projects and macros are never executed.')


def render_resources(store, workspace):
    class Reports(DbtOperations):
        def __init__(self):
            self.store = store
    reports = Reports()
    projects = store.rows('SELECT project_id,root_path,run_id FROM dbt_projects WHERE workspace_id=? ORDER BY root_path', [workspace])
    if not projects:
        return
    with st.expander('dbt resources and macro impact'):
        choices = {r['project_id']: r['root_path'] for r in projects}
        project = st.selectbox('dbt project', list(choices), format_func=choices.get, key='dbt_project_' + workspace)
        revision = next(p['run_id'] for p in projects if p['project_id'] == project)
        paging_key = 'dbt_resource_pages_' + workspace
        if st.session_state.get(paging_key, {}).get('context') != (project, revision):
            st.session_state[paging_key] = {'context': (project, revision), 'cursors': [None]}
        cursors = st.session_state[paging_key]['cursors']
        resources = reports._dbt_resources(workspace, QueryOptions(limit=100, max_chars=100000,
            cursor=cursors[-1]), project_id=project)
        rows = resources['items']
        st.caption(f"Resource page {len(cursors)} · {resources['total']} resources")
        previous, following = st.columns(2)
        if previous.button('Previous dbt resources', disabled=len(cursors) == 1):
            cursors.pop()
            st.rerun()
        if following.button('Next dbt resources', disabled=not resources['next_cursor']):
            cursors.append(resources['next_cursor'])
            st.rerun()
        st.dataframe(rows, column_order=['name', 'resource_type', 'package_name', 'version', 'enabled', 'resource_id'],
                     hide_index=True, alt='dbt resources, types and stable identities')
        if not rows:
            return
        names = {r['resource_id']: f"{r['resource_type']} · {r['name']}" + (f" v{r['version']}" if r['version'] else '') for r in rows}
        selected = st.selectbox('dbt resource', list(names), format_func=names.get, key='dbt_resource_' + workspace)
        detail = reports._dbt_resource(workspace, QueryOptions(detail_level='detailed'), selected)
        st.json(detail.get('metadata', {}), expanded=False)
        direction = st.selectbox('Resource impact direction', ['downstream', 'upstream'], key='dbt_direction_' + workspace)
        dependencies = reports._dbt_dependencies(workspace, QueryOptions(), selected, direction=direction)
        if not dependencies['complete']:
            st.caption(f"Showing {dependencies['count']} of {dependencies['total']} dependency records. Use the paged CLI/MCP report for the full traversal.")
        labels = {r['resource_id']: r['name'] for r in store.rows(
            'SELECT resource_id,name FROM dbt_resources WHERE workspace_id=? AND project_id=?', [workspace, project])}
        dependencies = [{**r, 'source': labels.get(r['source_id'], r['source_id']),
                         'target': labels.get(r['target_id'], r['target_id'])} for r in dependencies['items']]
        st.dataframe(dependencies, column_order=['source', 'target', 'kind', 'status', 'depth', 'cycle_or_repeated'],
                     hide_index=True, alt='Typed dbt dependencies and macro consumers')
        for support in detail.get('evidence', []):
            st.caption(f"{support['origin']} · lines {support['start_line']}–{support['end_line']}" +
                       (f" · {support['json_pointer']}" if support['json_pointer'] else ''))
            st.code(support['excerpt'], language=None)
