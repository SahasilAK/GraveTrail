"""Source-free selectable SVG column graph."""
from typing import Any

import streamlit as st

from dataforge.configuration import VisualizationSettings


def resolve_selection(scene: dict[str, Any], event: dict[str, Any] | None) -> dict[str, str] | None:
    if not isinstance(event, dict) or event.get('trace_key') != scene['trace_key']:
        return None
    items = scene['edges'] if event.get('kind') == 'edge' else scene['nodes']
    for item in items:
        if item['id'] == event.get('id') and event.get('kind') == item.get('kind', 'edge'):
            return {k: event[k] for k in ('trace_key', 'kind', 'id')}
    return None


_HTML = '''<div class="graph"><div class="toolbar"><button class="fit">Fit graph</button>
<button class="plus" aria-label="Zoom in">+</button><button class="minus" aria-label="Zoom out">−</button>
<input class="find" aria-label="Find a column" placeholder="Find a column"><span>Drag the background to pan</span></div>
<svg aria-label="Column lineage graph" role="group"><defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor"/></marker></defs><g class="stage"></g></svg>
<div class="legend">Solid: value · Dashed: selection, filter, join, rowset, partition or order · Select a box for logic and source</div></div>'''
_CSS = '''.graph{font:14px sans-serif;color:var(--st-text-color);background:var(--st-background-color);border:1px solid var(--st-border-color);border-radius:8px}.toolbar{display:flex;gap:8px;align-items:center;padding:10px;flex-wrap:wrap}button,input{font:inherit;color:inherit;background:var(--st-secondary-background-color);border:1px solid var(--st-border-color);border-radius:5px;padding:6px}svg{width:100%;height:480px;touch-action:none}.edge{stroke:var(--st-text-color);fill:none;opacity:.6;cursor:pointer}.node{cursor:pointer}.node rect{fill:var(--st-secondary-background-color);stroke:var(--st-text-color)}.node.transformation rect{stroke:var(--st-primary-color);stroke-width:2}.chosen rect,.chosen.edge{stroke:var(--st-primary-color);stroke-width:4;opacity:1}text{fill:var(--st-text-color);font-size:12px}.legend{padding:10px}.node:focus rect,.edge:focus{stroke-width:4}'''
_JS = r'''export default function(c){
 const root=c.parentElement, d=c.data.scene, svg=root.querySelector('svg'), stage=root.querySelector('.stage');
 const ns='http://www.w3.org/2000/svg', make=(tag,attrs,parent)=>{let e=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,v));parent.appendChild(e);return e};
 const bounds=d.bounds, fitted=Array.isArray(bounds)?bounds:[bounds.x,bounds.y,bounds.width,bounds.height];
 if(root._traceKey!==d.trace_key){root._box=[...fitted];root._traceKey=d.trace_key}
 const view=()=>svg.setAttribute('viewBox',root._box.join(' ')), zoom=f=>{let b=root._box;root._box=[b[0]+b[2]*(1-f)/2,b[1]+b[3]*(1-f)/2,b[2]*f,b[3]*f];view()};view();stage.replaceChildren();
 const pick=(kind,id)=>c.setStateValue('selection',{trace_key:d.trace_key,kind,id});
 const bind=(e,kind,id)=>{e.onclick=()=>pick(kind,id);e.onkeydown=v=>{if(v.key==='Enter'||v.key===' '){v.preventDefault();pick(kind,id)}}};
 for(const e of d.edges){let p=make('path',{d:e.path,class:'edge','marker-end':'url(#arrow)',tabindex:0,role:'button','aria-label':e.roles.join(', ')||'Output'},stage);if(e.roles.some(r=>r!=='value'))p.setAttribute('stroke-dasharray','6 4');bind(p,'edge',e.id);make('title',{},p).textContent=e.roles.join(', ')+(e.context_only?' (context only)':'');if(c.data.selection?.id===e.id)p.classList.add('chosen')}
 for(const n of d.nodes){let g=make('g',{class:'node '+n.kind,transform:`translate(${n.x},${n.y})`,tabindex:0,role:'button','aria-label':n.label},stage);make('rect',{width:n.width,height:n.height,rx:n.kind==='transformation'?4:12},g);let t=make('text',{x:10,y:24},g);t.textContent=n.label.length>34?n.label.slice(0,33)+'…':n.label;make('title',{},g).textContent=n.label+' · '+n.status+(n.cycle?' · cycle':'');bind(g,n.kind,n.id);g.dataset.label=n.label.toLowerCase();if(c.data.selection?.id===n.id||!c.data.selection&&n.is_root)g.classList.add('chosen')}
 root.querySelector('.fit').onclick=()=>{root._box=[...fitted];view()};root.querySelector('.plus').onclick=()=>zoom(.8);root.querySelector('.minus').onclick=()=>zoom(1.25);
 svg.onwheel=e=>{e.preventDefault();zoom(e.deltaY>0?1.1:.9)};
 let drag=null;svg.onpointerdown=e=>{if(e.target===svg){drag=[e.clientX,e.clientY,...root._box];svg.setPointerCapture(e.pointerId)}};svg.onpointermove=e=>{if(drag){root._box=[drag[2]-(e.clientX-drag[0])*drag[4]/svg.clientWidth,drag[3]-(e.clientY-drag[1])*drag[5]/svg.clientHeight,drag[4],drag[5]];view()}};svg.onpointerup=()=>drag=null;svg.onpointercancel=()=>drag=null;
 root.querySelector('.find').oninput=e=>{stage.querySelectorAll('.node').forEach(n=>n.classList.toggle('chosen',!!e.target.value&&n.dataset.label.includes(e.target.value.toLowerCase())))};
}'''
_COMPONENT = st.components.v2.component('column_lineage_graph', html=_HTML, css=_CSS, js=_JS)


def column_graph_view(scene: dict[str, Any], *, key: str, selection: dict[str, str] | None,
                      appearance: VisualizationSettings) -> Any:
    return _COMPONENT(data={'scene': scene, 'selection': selection}, key=key,
                      default={'selection': None}, on_selection_change=lambda: None, height='content')
