"""Source-free selectable SVG column graph."""
from typing import Any

import streamlit as st

from dataforge.configuration import VisualizationSettings
from dataforge.exports import SVG_PAN_JS


def resolve_selection(scene: dict[str, Any], event: dict[str, Any] | None) -> dict[str, str] | None:
    if not isinstance(event, dict) or event.get('trace_key') != scene['trace_key']:
        return None
    kind = event.get('kind')
    items = scene['edges'] if kind == 'edge' else scene['cards'] if kind == 'card' else scene['nodes']
    for item in items:
        if item['id'] == event.get('id') and event.get('kind') == item.get('kind', 'edge'):
            return {k: event[k] for k in ('trace_key', 'kind', 'id')}
    return None


_HTML = '''<div class="graph"><div class="toolbar"><button class="fit">Fit graph</button>
<button class="plus" aria-label="Zoom in">+</button><button class="minus" aria-label="Zoom out">−</button>
<input class="find" aria-label="Find a column" placeholder="Find a column"><span>Drag the graph to pan</span></div>
<svg aria-label="Column lineage graph" role="group"><defs><marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto"><path d="M 2 1.5 L 6.5 4 L 2 6.5" stroke-width="1.25"/></marker></defs><g class="stage"></g></svg>
<div class="legend">Solid lines carry values. Dashed lines show context such as filters, joins, or ordering. Select a card header, column, or link for logic.</div></div>'''
_CSS = '''
.graph{font:14px sans-serif;color:var(--st-text-color);background:var(--st-background-color);border:1px solid var(--st-border-color);border-radius:8px}
.toolbar{display:flex;gap:8px;align-items:center;padding:10px;flex-wrap:wrap}
button,input{font:inherit;color:inherit;background:var(--st-secondary-background-color);border:1px solid var(--st-border-color);border-radius:5px;padding:6px}
svg{display:block;width:100%;height:clamp(480px,60vh,620px);touch-action:none;user-select:none;cursor:grab}
svg.panning,svg.panning *{cursor:grabbing}
.edge{stroke:var(--st-text-color);stroke-width:1.25;stroke-linecap:round;fill:none;opacity:.65;cursor:pointer}
marker path{fill:none;stroke:var(--st-text-color);stroke:context-stroke;stroke-linecap:round;stroke-linejoin:round}
.card-outline{fill:var(--st-background-color);stroke:var(--st-border-color)}
.item{cursor:pointer}
.header rect{fill:var(--st-secondary-background-color);stroke:var(--st-border-color)}
.row rect{fill:transparent;stroke:var(--st-border-color)}
.item:focus{outline:none}
.item:is(:focus,.chosen,.match,:hover) rect{stroke:var(--st-primary-color);stroke-width:2}
.edge:is(:focus,.chosen,:hover){stroke:var(--st-primary-color);stroke-width:1.85;opacity:1}
text{fill:var(--st-text-color);font-size:13px}
.header .name{font-weight:650}.scope{font-size:11px;opacity:.75}
.legend{padding:10px}
'''
_JS = SVG_PAN_JS + r'''export default function(c){
 const root=c.parentElement, d=c.data.scene, svg=root.querySelector('svg'), stage=root.querySelector('.stage');
 const ns='http://www.w3.org/2000/svg', make=(tag,attrs,parent)=>{let e=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,v));parent.appendChild(e);return e};
 const bounds=d.bounds, fitted=Array.isArray(bounds)?bounds:[bounds.x,bounds.y,bounds.width,bounds.height];
 if(root._traceKey!==d.trace_key){root._box=[...fitted];root._traceKey=d.trace_key}
 const view=()=>svg.setAttribute('viewBox',root._box.join(' ')), zoom=f=>{let b=root._box;root._box=[b[0]+b[2]*(1-f)/2,b[1]+b[3]*(1-f)/2,b[2]*f,b[3]*f];view()};view();stage.replaceChildren();
 const pick=(kind,id)=>c.setStateValue('selection',{trace_key:d.trace_key,kind,id});
 const bind=(e,kind,id)=>{e.onclick=()=>pick(kind,id);e.onkeydown=v=>{if(v.key==='Enter'||v.key===' '){v.preventDefault();pick(kind,id)}}};
 const rowLabels=new Map(d.cards.flatMap(card=>card.rows.map(row=>[row.id,row.label])));
 for(const e of d.links){
   const label=rowLabels.get(e.source)+' → '+rowLabels.get(e.target)+' · '+e.roles.join(', ')+(e.context_only?' (context only)':'');
   const p=make('path',{d:e.path,class:'edge','marker-end':'url(#arrow)',tabindex:0,role:'button','aria-label':label},stage);
   if(e.context_only||!e.roles.includes('value'))p.setAttribute('stroke-dasharray','4 5');
   bind(p,'edge',e.id);make('title',{},p).textContent=label;
   if(c.data.selection?.id===e.id)p.classList.add('chosen');
 }
 const labelText=(parent,label,y,cls,width)=>{
   const t=make('text',{x:10,y,class:cls},parent);
   t.textContent=label.length>35?label.slice(0,34)+'…':label;
   if(t.getComputedTextLength()>width-20){t.setAttribute('textLength',width-20);t.setAttribute('lengthAdjust','spacingAndGlyphs')}
 };
 const item=(parent,n,kind,cls,label)=>{
   const g=make('g',{class:'item '+cls,tabindex:0,role:'button','aria-label':label},parent);
   make('title',{},g).textContent=label;bind(g,kind,n.id);g.dataset.label=label.toLowerCase();
   if(c.data.selection?.id===n.id||!c.data.selection&&n.is_root)g.classList.add('chosen');
   return g;
 };
 for(const card of d.cards){
   const g=make('g',{transform:`translate(${card.x},${card.y})`},stage);
   make('rect',{class:'card-outline',width:card.width,height:card.height,rx:6},g);
   const heading=item(g,card,'card','header',card.label+(card.scope?' · '+card.scope:''));
   make('rect',{width:card.width,height:card.header,rx:5},heading);
   labelText(heading,card.label,21,'name',card.width);
   if(card.scope)labelText(heading,card.scope,37,'scope',card.width);
   for(const row of card.rows){
     const r=item(g,row,'column','row',row.label);
     r.setAttribute('transform',`translate(0,${row.y})`);
     make('rect',{width:card.width,height:row.height},r);
     labelText(r,row.row_label,17,'name',card.width);
   }
 }
 root.querySelector('.fit').onclick=()=>{root._box=[...fitted];view()};root.querySelector('.plus').onclick=()=>zoom(.8);root.querySelector('.minus').onclick=()=>zoom(1.25);
 svg.onwheel=e=>{e.preventDefault();zoom(e.deltaY>0?1.1:.9)};
 root._stopPan?.();
 const stopPan=bindSvgPan(svg,stage,()=>root._box,next=>{root._box=next;view()});
 root._stopPan=stopPan;
 const find=root.querySelector('.find'), highlight=()=>{
   const value=find.value.trim().toLowerCase();
   stage.querySelectorAll('.item').forEach(n=>n.classList.toggle('match',!!value&&n.dataset.label.includes(value)));
 };
 find.oninput=highlight;highlight();
 return stopPan;
}'''
_COMPONENT = st.components.v2.component('column_lineage_graph', html=_HTML, css=_CSS, js=_JS)


def column_graph_view(scene: dict[str, Any], *, key: str, selection: dict[str, str] | None,
                      appearance: VisualizationSettings) -> Any:
    graph = {'trace_key': scene['trace_key'], 'cards': scene['cards'], 'links': scene['links'],
             'bounds': scene['card_bounds']}
    return _COMPONENT(data={'scene': graph, 'selection': selection}, key=key,
                      default={'selection': None}, on_selection_change=lambda: None, height='content')
