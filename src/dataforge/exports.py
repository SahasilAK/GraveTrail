"""Portable reports and an offline, dependency-free interactive SVG graph."""
from __future__ import annotations

import csv
import html
import io
import json
import zipfile
from typing import TYPE_CHECKING, Any

import networkx as nx

from dataforge.asset_identity import asset_job
from dataforge.configuration import VisualizationSettings
from dataforge.excel_exports import lineage_xlsx as lineage_xlsx
from dataforge.ingestion import safe_relative

if TYPE_CHECKING:
    from dataforge.graph import LineageGraph
    from dataforge.store import Store


def path_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a lineage report into rows while preserving path and evidence markers."""
    rows = []
    for path in report["paths"]:
        common = {"path_id": path["path_id"], "path": " -> ".join(path["nodes"]),
                  "direction": report["direction"], "boundary": path["boundary"],
                  "report_truncated": report["truncated"],
                  'report_complete': report.get('complete', not report['truncated']),
                  'unresolved_support_count': len(report.get('boundaries', []))}
        if not path["steps"]:
            rows.append({**common, "step": 0, "source": path["nodes"][0], "target": ""})
        for i, step in enumerate(path["steps"], 1):
            for evidence in step["evidence"] or [{}]:
                rows.append({**common, "step": i, "source": step["source"], "target": step["target"],
                             "intermediates": ", ".join(step["intermediates"]), **evidence})
    return rows


COPY_JS = r"""
async function copyText(text, target=document.body) {
 try {await navigator.clipboard.writeText(text);return true} catch (_) {
   const input=document.createElement('textarea');input.value=text;input.style.position='fixed';input.style.opacity='0';
   target.appendChild(input);input.select();
   let copied=false;try{copied=document.execCommand('copy')}catch(_){}finally{input.remove()}
   return copied;
 }
}
"""


GRAPH_CSS = """
.df-graph{font:14px/1.5 system-ui,sans-serif;color:var(--st-text-color,#23334a);background:var(--st-background-color,#fff);padding:12px;box-sizing:border-box;
--node-neutral:#edf0f4;--node-unresolved:#fff0d4;--node-temporary:#ece7f7;--node-source:#e0efeb;--node-table:#e3ecfb;--node-text:#23334a;--node-border:#8d9cb1}
.df-graph .toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding:0 0 12px}
.df-graph button,.df-graph input{font:inherit;min-height:36px;padding:6px 12px;border:1px solid var(--st-border-color,#bdc8d6);border-radius:7px;background:transparent;color:inherit;box-sizing:border-box;max-width:100%}
.df-graph button{cursor:pointer;touch-action:manipulation}.df-graph button:active{transform:scale(.97)}
.df-graph :is(button,input):focus-visible{outline:2px solid var(--st-primary-color,#2869c7);outline-offset:3px}
.df-graph svg{display:block;width:100%;height:clamp(420px,60vh,560px);border:1px solid var(--st-border-color,#bdc8d6);border-radius:10px;touch-action:none;user-select:none;cursor:grab;background:var(--st-secondary-background-color,#f5f7fa)}
.df-graph svg.panning,.df-graph svg.panning *{cursor:grabbing}
.df-graph .node{cursor:pointer}.df-graph .node:focus rect,.df-graph .edge:focus{stroke:#c47b18;stroke-width:4;outline:none}
.df-graph .edge{cursor:pointer;stroke:#829ab1;stroke-width:2;stroke-linecap:round;fill:none}
.df-graph .chosen{stroke:#d67d0d!important;stroke-width:4!important}
.df-graph .edge.chosen{stroke-width:var(--df-selected-edge-width,4)!important}
.df-graph .column-link.chosen{stroke-width:1.85!important}
.df-graph .detail{white-space:pre-wrap;overflow-wrap:anywhere;max-height:260px;overflow:auto;font:13px/1.7 ui-monospace,Consolas,monospace;padding:12px;border-radius:8px;background:var(--st-secondary-background-color,#f5f7fa)}
.df-graph .hint{font-size:12px;color:inherit;opacity:.8}
.df-graph .status{font-size:12px;min-height:18px}
.df-graph[data-themed]{color:var(--node-text);background:var(--graph-bg);color-scheme:var(--graph-mode)}
.df-graph[data-themed] svg{background:var(--graph-bg);border-color:var(--graph-border)}
.df-graph[data-themed] :is(button,input,.detail){background:var(--graph-surface);border-color:var(--graph-border)}
.df-graph[data-themed] .edge{stroke:var(--graph-edge)}
.df-graph[data-themed] :is(.edge,.column-link).chosen{stroke:var(--graph-path)!important}
.df-graph[data-themed] rect.chosen,.df-graph[data-themed] .node:focus rect{stroke:var(--graph-selected)!important;stroke-width:3!important}
.df-graph[data-themed] .edge:focus{stroke:var(--graph-path)}
.df-graph[data-themed] :is(button,input):focus-visible{outline-color:var(--graph-path)}
.df-graph[data-light] :is(rect.chosen,.node:focus rect,.edge.chosen,.edge:focus){filter:drop-shadow(1px 0 0 var(--node-text)) drop-shadow(-1px 0 0 var(--node-text)) drop-shadow(0 1px 0 var(--node-text)) drop-shadow(0 -1px 0 var(--node-text))}
.df-graph[data-light] :is(button,input):focus-visible{outline-color:var(--node-text)}
.df-graph .copy-node{cursor:pointer}.df-graph .copy-node:focus{outline:2px solid var(--st-primary-color,#2869c7)}
.df-graph .expand-node{cursor:pointer}.df-graph .expand-node:focus{outline:2px solid var(--st-primary-color,#2869c7)}
.df-graph .node-columns rect{fill:var(--graph-surface,var(--node-neutral));stroke:var(--graph-border,var(--node-border))}
.df-graph .node-columns line{stroke:var(--graph-border,var(--node-border))}
.df-graph .node-columns text{fill:var(--node-text);font-size:13px}
.df-graph .node-columns .column-note{font-size:11px;opacity:.75}
.df-graph .column-link{fill:none;stroke:var(--graph-edge,#829ab1);stroke-width:1.25;stroke-dasharray:4 5;stroke-linecap:round}
.df-graph marker path{fill:none;stroke:var(--graph-edge,#829ab1);stroke:context-stroke;stroke-linecap:round;stroke-linejoin:round}
.df-graph:fullscreen{width:100vw;height:100dvh;display:flex;flex-direction:column;overflow:auto}
.df-graph:fullscreen svg{flex:1;min-height:200px;height:auto}
.df-graph:fullscreen .detail{max-height:20vh;flex-shrink:0}
@media(prefers-color-scheme:dark){.df-graph{--node-neutral:#303b48;--node-unresolved:#4c3823;--node-temporary:#3b3354;--node-source:#203f3d;--node-table:#273d58;--node-text:#edf2f9;--node-border:#7489a3}}
@media(prefers-reduced-motion:reduce){.df-graph button:active{transform:none}}
@media(prefers-contrast:more){.df-graph .hint{opacity:1}.df-graph button,.df-graph input{border-color:currentColor}}
"""


SVG_PAN_JS = r"""
function bindSvgPan(svg, stage, getBox, setBox) {
 const listeners=new AbortController(), options={signal:listeners.signal};
 let drag=null, frame=null, suppressClick=false;
 const resetPreview=()=>{
   if(frame!==null){cancelAnimationFrame(frame);frame=null}
   stage.style.transform='';
   svg.classList.remove('panning');
 };
 svg.addEventListener('pointerdown',e=>{
   if(!e.isPrimary||e.button!==0)return;
   const matrix=svg.getScreenCTM()?.inverse();
   if(!matrix)return;
   suppressClick=false;
   drag={id:e.pointerId,x:e.clientX,y:e.clientY,matrix,moved:false,dx:0,dy:0};
   // Keep a simple click on its original element, even with pointer capture.
   e.target.setPointerCapture(e.pointerId);
 },options);
 svg.addEventListener('pointermove',e=>{
   if(e.pointerId!==drag?.id)return;
   const dx=e.clientX-drag.x,dy=e.clientY-drag.y;
   if(!drag.moved){
     if(Math.hypot(dx,dy)<4)return;
     drag.moved=true;
     svg.classList.add('panning');
   }
   const {a,b,c,d}=drag.matrix;
   drag.dx=a*dx+c*dy;drag.dy=b*dx+d*dy;
   // Move the scene without invalidating the SVG viewport on every pointer event.
   if(frame===null)frame=requestAnimationFrame(()=>{
     frame=null;
     stage.style.transform=`translate(${drag.dx}px,${drag.dy}px)`;
   });
 },options);
 const finish=e=>{
   if(e.pointerId!==drag?.id)return;
   suppressClick=drag.moved;
   if(drag.moved){
     const [x,y,width,height]=getBox();
     resetPreview();
     setBox([x-drag.dx,y-drag.dy,width,height]);
   }
   drag=null;
 };
 for(const event of ['pointerup','pointercancel','lostpointercapture'])svg.addEventListener(event,finish,options);
 for(const event of ['click','dblclick'])svg.addEventListener(event,e=>{
   if(suppressClick&&e.detail){e.preventDefault();e.stopImmediatePropagation()}
 },{...options,capture:true});
 return ()=>{listeners.abort();if(drag?.moved)resetPreview();drag=null};
}
"""


GRAPH_JS = COPY_JS + SVG_PAN_JS + r"""
function mountGraph(root, data, notify, navigate) {
 if(root._graphCleanup)root._graphCleanup();
 const svg=root.querySelector('svg'), stage=root.querySelector('.stage'), details=root.querySelector('.detail');
 const container=root.querySelector('.df-graph'),status=root.querySelector('.status');
 const theme=data.theme;
 if(data.boundaries?.length)status.textContent='Unresolved evidence: '+data.boundaries.length+' support(s); traversal stops where accepted support is absent.';
 container.toggleAttribute('data-themed',!!theme);
 container.toggleAttribute('data-light',theme?.mode==='light');
 if(theme){
   const tokens={'node-text':theme.text,'graph-bg':theme.graph,'graph-mode':theme.mode,'graph-border':theme.border,
     'graph-surface':theme.surface,'graph-edge':theme.edge,'graph-path':theme.path,'graph-selected':theme.selected};
   Object.entries(tokens).forEach(([key,value])=>container.style.setProperty('--'+key,value));
 }else{
   ['node-text','graph-bg','graph-mode','graph-border','graph-surface','graph-edge','graph-path','graph-selected'].forEach(key=>container.style.removeProperty('--'+key));
 }
 let clickTimer=null;
 const appearance=data.appearance||{},labels=appearance.graph_labels||'compact';
 const edgeWidth=appearance.graph_edge_width||2;
 root.querySelector('.df-graph').style.setProperty('--df-selected-edge-width',edgeWidth+2);
 const ns='http://www.w3.org/2000/svg';
 const make=(tag,attrs,parent)=>{const e=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,v));parent.appendChild(e);return e};
 stage.replaceChildren();
 const nodes=new Map(data.nodes.map(n=>[n.asset_id,n]));
 const nodeLabel=n=>n.job_id&&n.job_id!=='workspace'?n.name+' [job: '+n.job_id+']':n.name;
 const fitted=[...data.bounds];
 let box=[...fitted];
 const view=()=>svg.setAttribute('viewBox',box.join(' '));view();
 const expanded=root._expandedColumns??=new Set(), frames=new Map(), edgePaths=[];
 const highlighted=root._graphHighlight??={nodes:new Set(),edges:new Set()};
 let columnLayer, activeLinks=[];
 const reflow=()=>{
   const offsets=new Map(), positions=new Map();
   let bottom=data.bounds[3];
   for(const n of data.nodes){
     const frame=frames.get(n.asset_id), offset=offsets.get(n.x)||0;
     const y=n.y+offset;
     frame.element.setAttribute('transform',`translate(${n.x},${y})`);
     positions.set(n.asset_id,y);
     offsets.set(n.x,offset+frame.extra);
     bottom=Math.max(bottom,y+180+frame.extra);
   }
   fitted[3]=bottom;
   data.edges.forEach((edge,i)=>{
     const a=nodes.get(edge.source),b=nodes.get(edge.target),p=edgePaths[i];
     const y1=positions.get(edge.source)+24,y2=positions.get(edge.target)+24;
     if(a.asset_id===b.asset_id){
       p.setAttribute('transform',`translate(0,${y1-a.y-24})`);
     }else{
       const x1=a.x+a.width,x2=b.x;
       p.setAttribute('d',`M ${x1} ${y1} C ${x1+70} ${y1} ${x2-70} ${y2} ${x2} ${y2}`);
     }
   });
   if(columnLayer){
     columnLayer.replaceChildren();
     for(const {edge, link, index} of activeLinks){
       const a=nodes.get(edge.source), b=nodes.get(edge.target);
       const y1=positions.get(edge.source)+frames.get(edge.source).rows.get(link.source);
       const y2=positions.get(edge.target)+frames.get(edge.target).rows.get(link.target);
       const x1=a.x+a.width, x2=b.x>a.x?b.x:b.x+b.width;
       const bend=x2>x1?(x1+x2)/2:Math.max(x1,x2)+46;
       const end=y1===y2&&x1===x2?y2+5:y2;
       const path=make('path',{d:`M ${x1} ${y1} C ${bend} ${y1} ${bend} ${end} ${x2} ${end}`,
                              class:'column-link','data-column-edge':index,'marker-end':'url(#df-column-arrow)'},columnLayer);
       if(highlighted.edges.has(index))path.classList.add('chosen');
       make('title',{},path).textContent=`${a.name}.${link.source} → ${b.name}.${link.target}`;
     }
   }
 };
 const refreshColumns=()=>{
   const required=new Map();
   const requireRow=(asset,name)=>{
     if(!required.has(asset))required.set(asset,new Set());
     required.get(asset).add(name);
   };
   activeLinks=[];
   data.edges.forEach((edge,i)=>{
     if(!expanded.has(edge.source)&&!expanded.has(edge.target))return;
     for(const link of data.column_links?.[i]||[]){
       if(!link.value)continue;
       activeLinks.push({edge,link,index:i});
       requireRow(edge.source,link.source);
       requireRow(edge.target,link.target);
     }
   });
   for(const [asset,frame] of frames)frame.drawColumns?.(required.get(asset));
   reflow();
 };
 const applyHighlight=()=>{
   stage.querySelectorAll('[data-node]').forEach(e=>e.classList.toggle('chosen',highlighted.nodes.has(e.dataset.node)));
   edgePaths.forEach((path,i)=>path.classList.toggle('chosen',highlighted.edges.has(i)));
   columnLayer?.querySelectorAll('[data-column-edge]').forEach(path=>{
     path.classList.toggle('chosen',highlighted.edges.has(Number(path.dataset.columnEdge)));
   });
 };
 const highlight=(ids, edges=[])=>{
   highlighted.nodes=ids;
   highlighted.edges=new Set(edges);
   applyHighlight();
 };
 const inspectNode=(n,emit=true)=>{
   let related=new Set([n.asset_id]),pending=[n.asset_id];
   while(pending.length){let id=pending.pop();data.edges.forEach(e=>{if(e.target===id&&!related.has(e.source)){related.add(e.source);pending.push(e.source)}})}
   highlight(related,data.edges.flatMap((edge,i)=>related.has(edge.source)&&related.has(edge.target)?[i]:[]));
   details.textContent=nodeLabel(n)+'\n'+(n.temporary?'Temporary asset':'Persistent or external asset')+'\n'+data.edges.filter(e=>e.source===n.asset_id||e.target===n.asset_id).map(e=>nodeLabel(nodes.get(e.source))+' → '+nodeLabel(nodes.get(e.target))+'\n'+e.evidence.map(v=>(v.relative_path||'')+':'+v.start_line+'–'+v.end_line+' '+(v.kind||'')+' ['+(v.status||'')+']').join('\n')).join('\n\n')+(data.boundaries||[]).filter(e=>e.source_id===n.asset_id||e.target_id===n.asset_id).map(e=>'\nUnresolved evidence: '+(e.relative_path||'')+':'+(e.start_line||'')+' ['+(e.edge_id||'')+']\n'+(e.code||'')).join('\n');
   if(emit&&notify)notify({node:n.asset_id});
 };
 data.edges.forEach((edge,i)=>{
   const a=nodes.get(edge.source),b=nodes.get(edge.target);
   const d=edge.path;
   const p=make('path',{d,'class':'edge','marker-end':'url(#df-arrow)','data-edge':i,tabindex:0,role:'button','aria-label':nodeLabel(a)+' to '+nodeLabel(b)},stage);
   edgePaths.push(p);
   p.style.strokeWidth=edgeWidth;
   const show=()=>{highlight(new Set([edge.source,edge.target]),[i]);details.textContent=nodeLabel(a)+' → '+nodeLabel(b)+'\n'+(edge.intermediates.length?'Via '+edge.intermediates.join(', ')+'\n':'')+edge.evidence.map(v=>(v.relative_path||'')+':'+v.start_line+'–'+v.end_line+' '+v.kind+'\n'+v.code).join('\n\n');if(notify)notify({edge:i})};
   p.onclick=show;p.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();show()}};
 });
 if(data.column_links)columnLayer=make('g',{class:'column-links'},stage);
 data.nodes.forEach(n=>{
   const element=make('g',{transform:`translate(${n.x},${n.y})`},stage);
   const frame={element,extra:0};
   frames.set(n.asset_id,frame);
   const columns=data.columns?.[n.asset_id], controlWidth=columns?82:52;
   const g=make('g',{'class':'node',tabindex:0,role:'button','aria-label':nodeLabel(n)},element);
   const role=theme&&(n.kind==='unresolved'?theme.selected:n.source?theme.source:n.target?theme.target:theme.intermediate);
   const semantic=theme&&appearance.graph_palette!=='neutral';
   const color=theme?(semantic?`color-mix(in srgb, ${role} 25%, ${theme.graph})`:theme.surface):appearance.graph_palette==='neutral'?'var(--node-neutral)':n.kind==='unresolved'?'var(--node-unresolved)':n.temporary?'var(--node-temporary)':n.source?'var(--node-source)':'var(--node-table)';
   make('rect',{width:n.width,height:48,rx:9,fill:color,stroke:theme?(semantic?role:theme.border):'var(--node-border)','data-node':n.asset_id},g);
   if(labels!=='hidden'){
     const text=make('text',{x:12,y:29,fill:'var(--node-text)','font-size':13},g);
     const label=nodeLabel(n);text.textContent=labels==='compact'&&label.length>22?label.slice(0,21)+'…':label;
     if(text.getComputedTextLength()>n.width-controlWidth){text.setAttribute('textLength',n.width-controlWidth);text.setAttribute('lengthAdjust','spacingAndGlyphs')}
   }
   make('title',{},g).textContent=nodeLabel(n);
   g.onclick=()=>{clearTimeout(clickTimer);inspectNode(n,false);clickTimer=setTimeout(()=>{if(notify)notify({node:n.asset_id})},350)};
   g.ondblclick=e=>{e.preventDefault();clearTimeout(clickTimer);if(navigate)navigate(n.asset_id);else inspectNode(n)};
   g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();if(e.key==='Enter'&&e.altKey&&navigate)navigate(n.asset_id);else inspectNode(n)}};
   const copy=make('g',{'class':'copy-node',transform:`translate(${n.width-(columns?62:32)},10)`,tabindex:0,role:'button','aria-label':'Copy '+n.name},element);
   make('rect',{width:26,height:28,rx:5,fill:color},copy);
   make('text',{x:5,y:20,fill:'var(--node-text)','font-size':19,'pointer-events':'none'},copy).textContent='⧉';
   make('title',{},copy).textContent='Copy '+n.name;
   copy.onclick=async e=>{e.stopPropagation();clearTimeout(clickTimer);status.textContent=await copyText(n.name,container)?'Copied '+n.name:'Copy failed. Select the name in the details and copy manually.'};
   copy.ondblclick=e=>{e.stopPropagation();e.preventDefault()};
   copy.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();copy.onclick(e)}};
   if(columns){
     const toggle=make('g',{class:'expand-node',transform:`translate(${n.width-32},10)`,tabindex:0,role:'button'},element);
     make('rect',{width:26,height:28,rx:5,fill:color},toggle);
     const icon=make('text',{x:13,y:20,fill:'var(--node-text)','font-size':18,'text-anchor':'middle','pointer-events':'none'},toggle);
     const title=make('title',{},toggle);
     let panel=null, previous='';
     frame.drawColumns=(required=[])=>{
       const open=expanded.has(n.asset_id);
       const names=open?[...new Set([...columns.names,...required])]:[...required];
       const signature=JSON.stringify([open,names]);
       if(signature===previous)return;
       previous=signature;
       title.textContent=(open?'Hide':'Show')+' final columns for '+n.name;
       toggle.setAttribute('aria-label',title.textContent);
       toggle.setAttribute('aria-expanded',open);
       icon.textContent=open?'−':'+';
       panel?.remove();panel=null;frame.extra=0;frame.rows=new Map();
       if(!open&&!names.length)return;
       const rowHeight=26;
       frame.extra=(names.length+1)*rowHeight;
       panel=make('g',{class:'node-columns',transform:'translate(0,48)',role:'group',
                       'aria-label':'Final columns for '+n.name},element);
       make('rect',{width:n.width,height:frame.extra,rx:5},panel);
       const note=!open?'Linked columns':names.length?(columns.declared?'Declared columns':'Known columns'):'No final columns known';
       make('text',{x:10,y:17,class:'column-note'},panel).textContent=note;
       if(!names.length)return;
       const list=make('g',{role:'list','aria-label':note},panel);
       const labels=names.map((name,i)=>{
         const row=make('g',{role:'listitem','aria-label':name},list);
         const y=(i+1)*rowHeight;
         frame.rows.set(name,48+y+rowHeight/2);
         make('line',{x1:0,y1:y,x2:n.width,y2:y},row);
         make('title',{},row).textContent=name;
         const text=make('text',{x:10,y:y+17},row);
         text.textContent=name.length>35?name.slice(0,34)+'…':name;
         return text;
       });
       for(const text of labels.filter(text=>text.getComputedTextLength()>n.width-20)){
         text.setAttribute('textLength',n.width-20);
         text.setAttribute('lengthAdjust','spacingAndGlyphs');
       }
     };
     frame.drawColumns();
     toggle.onclick=()=>{expanded.has(n.asset_id)?expanded.delete(n.asset_id):expanded.add(n.asset_id);refreshColumns()};
     toggle.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();toggle.onclick()}};
   }
 });
 if(expanded.size){refreshColumns();box=[...fitted];view()}
 if(highlighted.nodes.size||highlighted.edges.size)applyHighlight();
 const fullscreen=root.querySelector('.fullscreen');
 const doc=container.ownerDocument;
 const syncFullscreen=()=>{fullscreen.textContent=container.matches(':fullscreen')?'Exit fullscreen':'Fullscreen'};
 fullscreen.onclick=async()=>{
   try{if(container.matches(':fullscreen'))await doc.exitFullscreen();else await container.requestFullscreen();syncFullscreen()}
   catch(_){status.textContent='Fullscreen is unavailable in this browser.'}
 };
 if(doc){doc.addEventListener('fullscreenchange',syncFullscreen);syncFullscreen()}
 root.querySelector('.fit').onclick=()=>{box=[...fitted];view()};
 const zoom=(f)=>{box=[box[0]+box[2]*(1-f)/2,box[1]+box[3]*(1-f)/2,box[2]*f,box[3]*f];view()};
 root.querySelector('.plus').onclick=()=>zoom(.8);root.querySelector('.minus').onclick=()=>zoom(1.25);
 svg.onwheel=e=>{e.preventDefault();zoom(e.deltaY>0?1.1:.9)};
 const stopPan=bindSvgPan(svg,stage,()=>box,next=>{box=next;view()});
 root.querySelector('.find').oninput=e=>{let value=e.target.value.toLowerCase();highlight(new Set(data.nodes.filter(n=>value&&nodeLabel(n).toLowerCase().includes(value)).map(n=>n.asset_id)))};
 root._graphCleanup=()=>{stopPan();clearTimeout(clickTimer);if(doc)doc.removeEventListener('fullscreenchange',syncFullscreen)};
 return root._graphCleanup;
}
"""

GRAPH_BODY = """<div class="df-graph"><div class="toolbar"><button class="fit">Fit graph</button><button class="plus" aria-label="Zoom in">+</button><button class="minus" aria-label="Zoom out">−</button><button class="fullscreen">Fullscreen</button><input class="find" aria-label="Find a node" placeholder="Find a node"><span class="hint">Select for evidence. Double-click a node (Alt+Enter) to focus it. Drag the graph to pan.</span></div><svg role="group" aria-label="Directed lineage graph"><defs>
<marker id="df-arrow" viewBox="0 0 12 12" refX="10" refY="6" markerWidth="12" markerHeight="12" markerUnits="userSpaceOnUse" orient="auto"><path d="M 3 2 L 9.5 6 L 3 10" stroke-width="1.6"/></marker>
<marker id="df-column-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto"><path d="M 2 1.5 L 6.5 4 L 2 6.5" stroke-width="1.25"/></marker>
</defs><g class="stage"></g></svg><div class="status" role="status"></div><pre class="detail" aria-live="polite">Select a relationship to inspect its evidence.</pre></div>"""


def graph_data(
    graph: LineageGraph,
    appearance: VisualizationSettings | None = None,
    *,
    theme: str | None = None,
) -> dict[str, Any]:
    """Build the positioned, serializable node and edge scene used by graph views."""
    appearance = appearance or VisualizationSettings()
    condensed = nx.condensation(graph.graph)
    groups = list(nx.topological_generations(condensed))
    width = min(700, max([215] + [len(n["name"]) * 7 + 24 for n in graph.nodes.values()])) if appearance.graph_labels == "full" else 215
    layer_gap, row_gap = 200, 76
    nodes = []
    for level, components in enumerate(groups):
        ids = sorted(n for c in components for n in condensed.nodes[c]["members"])
        for row, node in enumerate(ids):
            attrs = dict(graph.nodes[node])
            attrs.update(x=20 + level * (width + layer_gap), y=20 + row * (48 + row_gap), width=width,
                         source=graph.graph.in_degree(node) == 0,
                         target=graph.graph.out_degree(node) == 0, job_id=asset_job(attrs))
            nodes.append(attrs)
    edges = [{"source": s, "target": t, "evidence": a["evidence"], "intermediates": a.get("intermediates", [])}
             for s, t, a in graph.graph.edges(data=True)]
    by_id = {n['asset_id']: n for n in nodes}
    for edge in edges:
        a, b = by_id[edge['source']], by_id[edge['target']]
        x1, y1, x2, y2 = a['x'] + a['width'], a['y'] + 24, b['x'], b['y'] + 24
        edge['path'] = (f"M {x1} {y1} c 70 -80 {-a['width']-25} -80 {5-a['width']} 0"
                        if edge['source'] == edge['target'] else
                        f'M {x1} {y1} C {x1+70} {y1} {x2-70} {y2} {x2} {y2}')
    bounds = [-80, -80, max([780] + [n['x'] + n['width'] + 180 for n in nodes]),
              max([360] + [n['y'] + 180 for n in nodes])]
    from dataforge.theme_configuration import PALETTES

    scene = {"nodes": nodes, "edges": edges, "bounds": bounds,
        'boundaries': list(graph.unresolved_edges), 'complete': not graph.truncated and not graph.unresolved_edges,
        "appearance": appearance.model_dump(include={
        "graph_labels", "graph_palette", "graph_edge_width"})}
    if theme in PALETTES:
        scene["theme"] = PALETTES[theme]
    return scene


def graph_html(graph: LineageGraph, appearance: VisualizationSettings | None = None) -> str:
    """Create a self-contained HTML document for an interactive lineage graph."""
    data = json.dumps(graph_data(graph, appearance), default=str).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>GraveTrail lineage</title><style>body{margin:20px}' + GRAPH_CSS + '</style></head><body>'
            '<h1>GraveTrail lineage</h1><p>Static dependencies with source evidence. Logical ordering is not execution order.</p>'
            + GRAPH_BODY + '<script>' + GRAPH_JS + '\nmountGraph(document.body,' + data + ',null);</script></body></html>')


def report_csv(rows: list[dict[str, Any]]) -> str:
    """Serialize report rows as CSV while prefixing spreadsheet formula-like values."""
    if not rows:
        return ""
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    for row in rows:
        writer.writerow({k: "'" + str(v) if str(v).startswith(("=", "+", "-", "@", "\t", "\r")) else v for k, v in row.items()})
    return stream.getvalue()


def report_html(rows: list[dict[str, Any]]) -> str:
    """Render report rows as an HTML table with escaped headers and cell values."""
    header = "".join(f"<th>{html.escape(k)}</th>" for k in (rows[0] if rows else []))
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in r.values()) + "</tr>" for r in rows)
    return '<!doctype html><html lang="en"><meta charset="utf-8"><title>GraveTrail report</title><style>body{font:14px system-ui;margin:24px}table{border-collapse:collapse}td,th{padding:8px;border:1px solid #ccd;text-align:left;white-space:pre-wrap}</style><h1>GraveTrail report</h1><table><thead><tr>' + header + '</tr></thead><tbody>' + body + '</tbody></table></html>'


def source_bundle(
    store: Store,
    file_ids: list[str],
    versions: dict[str, str | list[str]] | None = None,
) -> bytes:
    """Package selected original source versions in a ZIP archive.

    Args:
        store: Workspace store used to retrieve source records and original content.
        file_ids: File IDs to include; repeated IDs are included once.
        versions: Optional per-file digest or digest list selecting archived versions.

    Returns:
        ZIP archive bytes containing the selected original files.
    """
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for fid in dict.fromkeys(file_ids):
            source = store.file(fid)
            selected = (versions or {}).get(fid)
            hashes = selected if isinstance(selected, list) else [selected]
            for digest in hashes:
                path = source['relative_path']
                if len(hashes) > 1:
                    path = digest + '/' + path
                archive.writestr(safe_relative(path), store.original(fid, digest))
    return out.getvalue()
