"""Transient reasoning display; the browser owns expansion and scroll position."""
import streamlit as st

_panel = st.components.v2.component(
    'ai_reasoning_panel',
    html='<details><summary>Model thinking</summary><p id="identity"></p><p id="trim"></p>'
         '<div id="body" tabindex="0" role="region" aria-label="Model thinking"></div>'
         '<button type="button">Jump to latest</button></details>',
    css='''#body {height:300px; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere;
        font-family:var(--st-font, sans-serif); border:1px solid var(--st-border-color);
        padding:0.5rem; box-sizing:border-box; overflow-anchor:none}
        summary,button {cursor:pointer} p {font-size:0.85em}''',
    js='''export default function({data,parentElement}) {
      const details=parentElement.querySelector('details');
      const body=parentElement.querySelector('#body');
      const button=parentElement.querySelector('button');
      const identity=parentElement.querySelector('#identity');
      const storageKey='ai_reasoning_'+data.scope;
      let state;
      try {state=JSON.parse(sessionStorage.getItem(storageKey)||'null')} catch(e) {}
      state=state||{open:false,top:0,follow:true};
      const save=()=>{try {sessionStorage.setItem(storageKey,JSON.stringify(state))}catch(e){}};
      details.open=state.open;
      details.ontoggle=()=>{state.open=details.open;save();
        if(details.open) body.scrollTop=state.follow?body.scrollHeight:state.top;};
      identity.textContent='Attempt '+data.attempt_id+' · '+data.state;
      parentElement.querySelector('#trim').textContent=data.trimmed?'Older displayed text was removed (64 KiB limit).':'';
      body.onscroll=null;
      body.textContent=data.text;
      body.scrollTop=state.follow?body.scrollHeight:state.top;
      body.onscroll=()=>{state.top=body.scrollTop;
        state.follow=body.scrollHeight-body.scrollTop-body.clientHeight<12;save();};
      button.onclick=()=>{state.follow=true;body.scrollTop=body.scrollHeight;state.top=body.scrollTop;save();};
      return ()=>{body.onscroll=null;details.ontoggle=null;button.onclick=null;};
    }''',
)


def render_reasoning(snapshot, workspace):
    if not snapshot or not snapshot['text'].strip():
        st.caption('No thinking/reasoning available')
        return
    _panel(data={**snapshot, 'scope': workspace + '_' + snapshot['run_id'] + '_' + snapshot['attempt_id']},
        key='reasoning_' + workspace + '_' + snapshot['run_id'] + '_' + snapshot['attempt_id'], height='content')


def reasoning_panel(jobs, job_id, workspace, run_id, active):
    # Recreate the scoped fragment with no timer after termination.
    @st.fragment(run_every=.5 if active else None)
    def refresh():
        record = jobs.read(job_id, workspace)
        snapshot = jobs.reasoning_snapshot(job_id, workspace, run_id) if hasattr(jobs, 'reasoning_snapshot') else None
        render_reasoning(snapshot, workspace)
        if active and record['status'] in {'completed', 'cancelled', 'failed', 'interrupted'}:
            st.rerun(scope='app')
    refresh()
