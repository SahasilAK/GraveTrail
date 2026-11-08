"""Source-free selectable SVG column graph."""
from typing import Any

import streamlit as st

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
<input class="find" aria-label="Find a column" placeholder="Find a column"><span>Drag a header to move a card. Drag the background or Alt-drag to pan.</span></div>
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
.item.header{cursor:grab}
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
 const existing=root._columnScene;
 if(existing?.stage===stage&&existing.key===d.trace_key)return existing.update(c);
 existing?.cleanup();
 const ns='http://www.w3.org/2000/svg', make=(tag,attrs,parent)=>{let e=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,v));parent.appendChild(e);return e};
 const bounds=d.bounds, fitted=Array.isArray(bounds)?bounds:[bounds.x,bounds.y,bounds.width,bounds.height];
 if(root._traceKey!==d.trace_key){root._box=[...fitted];root._cardMoves=new Map();root._traceKey=d.trace_key}
 const view=()=>svg.setAttribute('viewBox',root._box.join(' ')), zoom=f=>{let b=root._box;root._box=[b[0]+b[2]*(1-f)/2,b[1]+b[3]*(1-f)/2,b[2]*f,b[3]*f];view()};view();stage.replaceChildren();
 const content=document.createDocumentFragment(), items=new Map(), textLabels=[];
 let client=c, selected=null, rootColumn=null, stopPan=null;
 const select=id=>{
   if(selected===id)return;
   items.get(selected)?.classList.remove('chosen');
   selected=id;
   items.get(id)?.classList.add('chosen');
 };
 const pick=(kind,id)=>{
   select(id);
   client.setStateValue('selection',{trace_key:d.trace_key,kind,id});
 };
 const bind=(e,kind,id)=>{
   items.set(id,e);
   e.onclick=()=>pick(kind,id);
   e.onkeydown=v=>{if(v.key==='Enter'||v.key===' '){v.preventDefault();pick(kind,id)}};
 };
 const moves=root._cardMoves, cards=new Map(), rows=new Map(), parallel=new Map();
 for(const card of d.cards){
   const frame={...card,baseX:card.x,baseY:card.y,reroute:[]};
   cards.set(card.id,frame);
   for(const row of card.rows)rows.set(row.id,{frame,row});
 }
 for(const e of d.links){
   const a=rows.get(e.source),b=rows.get(e.target);
   const label=a.row.label+' → '+b.row.label+' · '+e.roles.join(', ')+(e.context_only?' (context only)':'');
   const p=make('path',{d:e.path,class:'edge','marker-end':'url(#arrow)',tabindex:0,role:'button','aria-label':label},content);
   if(e.context_only||!e.roles.includes('value'))p.setAttribute('stroke-dasharray','4 5');
   bind(p,'edge',e.id);make('title',{},p).textContent=label;
   const pair=e.source+'|'+e.target, offset=parallel.get(pair)||0;
   parallel.set(pair,offset+8);
   const route=()=>{
     const y1=a.frame.y+a.row.y+a.row.height/2, y2=b.frame.y+b.row.y+b.row.height/2;
     const moved=moves.has(a.frame.id)||moves.has(b.frame.id);
     p.setAttribute('d',moved?movedCardLink(a.frame,b.frame,y1,y2,Math.min(offset,40)):e.path);
   };
   a.frame.reroute.push(route);
   if(a.frame!==b.frame)b.frame.reroute.push(route);
 }
 const labelText=(parent,label,y,cls,width)=>{
   const t=make('text',{x:10,y,class:cls},parent);
   t.textContent=label.length>35?label.slice(0,34)+'…':label;
   textLabels.push([t,width-20]);
 };
 const item=(parent,n,kind,cls,label)=>{
   const g=make('g',{class:'item '+cls,tabindex:0,role:'button','aria-label':label},parent);
   make('title',{},g).textContent=label;bind(g,kind,n.id);g.dataset.label=label.toLowerCase();
   if(n.is_root)rootColumn=n.id;
   return g;
 };
 const place=(card,dx,dy)=>{
   card.x=card.baseX+dx;card.y=card.baseY+dy;
   card.element.setAttribute('transform',`translate(${card.x},${card.y})`);
 };
 for(const card of cards.values()){
   const g=make('g',{transform:`translate(${card.x},${card.y})`},content);
   card.element=g;
   if(moves.has(card.id))place(card,...moves.get(card.id));
   make('rect',{class:'card-outline',width:card.width,height:card.height,rx:6},g);
   const heading=item(g,card,'card','header',card.label+(card.scope?' · '+card.scope:''));
   heading.dataset.cardHandle=card.id;
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
 stage.appendChild(content);
 // Measure once after insertion so creating each row does not force SVG layout.
 for(const [label,width] of textLabels.filter(([label,width])=>label.getComputedTextLength()>width)){
   label.setAttribute('textLength',width);label.setAttribute('lengthAdjust','spacingAndGlyphs');
 }
 select(c.data.selection?.id??rootColumn);
 for(const id of moves.keys())cards.get(id)?.reroute.forEach(route=>route());
 root.querySelector('.fit').onclick=()=>{root._box=fitMovedCards(fitted,cards.values());view()};root.querySelector('.plus').onclick=()=>zoom(.8);root.querySelector('.minus').onclick=()=>zoom(1.25);
 svg.onwheel=e=>{e.preventDefault();zoom(e.deltaY>0?1.1:.9)};
 const startMove=target=>{
   const card=cards.get(target.closest('[data-card-handle]')?.dataset.cardHandle);
   if(!card)return;
   const [x,y]=moves.get(card.id)||[0,0];
   return (dx,dy)=>{
     if(x+dx||y+dy)moves.set(card.id,[x+dx,y+dy]);else moves.delete(card.id);
     place(card,x+dx,y+dy);
     card.reroute.forEach(route=>route());
   };
 };
 const find=root.querySelector('.find'), highlight=()=>{
   const value=find.value.trim().toLowerCase();
   stage.querySelectorAll('.item').forEach(n=>n.classList.toggle('match',!!value&&n.dataset.label.includes(value)));
 };
 find.oninput=highlight;highlight();
 const cleanup=()=>{stopPan?.();stopPan=null};
 const update=next=>{
   client=next;
   if(!stopPan)stopPan=bindSvgPan(svg,stage,()=>root._box,box=>{root._box=box;view()},startMove);
   return cleanup;
 };
 root._columnScene={stage,key:d.trace_key,update,cleanup};
 return update(c);
}'''
_COMPONENT = st.components.v2.component('column_lineage_graph', html=_HTML, css=_CSS, js=_JS)


def column_graph_view(scene: dict[str, Any], *, key: str, selection: dict[str, str] | None) -> Any:
    graph = {'trace_key': scene['trace_key'], 'cards': scene['cards'], 'links': scene['links'],
             'bounds': scene['card_bounds']}
    return _COMPONENT(data={'scene': graph, 'selection': selection}, key=key,
                      default={'selection': None}, on_selection_change=lambda: None, height='content')
