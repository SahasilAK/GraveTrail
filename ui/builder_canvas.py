"""Offline SVG authoring canvas; the same renderer powers HTML presentations."""
import json

import streamlit as st

from dataforge.lineage_builder import BuilderDocument

BODY = """
<div class="lb-root">
 <div class="lb-toolbar">
  <button data-action="fit">Fit diagram</button><button data-action="out" aria-label="Zoom out">−</button>
  <button data-action="in" aria-label="Zoom in">+</button><button data-action="full">Full screen</button>
  <button data-action="svg">SVG</button><button data-action="png">PNG</button>
  <span class="lb-status" role="status" aria-live="polite"></span>
 </div>
 <div class="lb-layout">
  <aside class="lb-palette"><label>Table catalog<input class="lb-search" placeholder="Find a table" aria-label="Find a table"></label><div class="lb-tables"></div></aside>
  <div class="lb-board"><svg class="lb-svg" tabindex="0" role="group" aria-label="Lineage canvas. Drag table headers to move. Connect an output port to an input port." viewBox="0 0 1200 700" preserveAspectRatio="xMidYMin meet"></svg></div>
 </div>
 <div class="lb-inspector"><span class="lb-selection">Select a table or relationship.</span>
  <input class="lb-label" aria-label="Relationship label" placeholder="Relationship label, e.g. Join" maxlength="500" hidden>
  <button data-action="label" hidden>Apply label</button><button data-action="remove" hidden>Remove</button>
 </div>
 <p class="lb-hint">Add a table from the catalog. Drag its header to move it. Drag a right column port to a left port, or select the two ports in order. Drag empty space to pan; scroll to zoom. Edits save automatically.</p>
</div>
"""

CSS = """
.lb-root{font:14px/1.5 var(--st-font,sans-serif);color:var(--st-text-color,#243449);--lb-bg:var(--st-background-color,#fff);--lb-card:var(--st-secondary-background-color,#f2f5f9);--lb-border:var(--st-border-color,#a3afbd);--lb-accent:var(--st-primary-color,#176db1)}
.lb-toolbar,.lb-inspector{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:10px 0}
.lb-root button,.lb-root input{font:inherit;color:inherit;background:var(--lb-bg);border:1px solid var(--lb-border);border-radius:5px;padding:7px 10px;min-height:36px;box-sizing:border-box}
.lb-root button{cursor:pointer}.lb-root button:disabled{opacity:.5;cursor:wait}.lb-root button:hover{border-color:var(--lb-accent)}
.lb-root :is(button,input,svg,[tabindex]):focus-visible{outline:2px solid var(--lb-accent);outline-offset:3px}
.lb-layout{display:grid;grid-template-columns:190px minmax(0,1fr);border:1px solid var(--lb-border);border-radius:8px;overflow:hidden}
.lb-palette{padding:12px;background:var(--lb-card);border-right:1px solid var(--lb-border);max-height:620px;overflow:auto}
.lb-search{display:block;width:100%;margin:8px 0 12px}.lb-tables button{display:block;text-align:left;width:100%;margin:7px 0;overflow-wrap:anywhere}.lb-tables small{display:block;opacity:.7}
.lb-board{min-width:0;overflow:hidden;background:var(--lb-bg)}.lb-svg{display:block;width:100%;height:620px;touch-action:none;background-image:radial-gradient(var(--lb-border) .6px,transparent .6px);background-size:20px 20px}
.lb-svg .lb-card{fill:var(--lb-card);stroke:var(--lb-border)}.lb-svg text{fill:var(--st-text-color,#243449);user-select:none}.lb-svg .lb-port{fill:var(--lb-bg);stroke:var(--lb-accent);stroke-width:2;cursor:crosshair}
.lb-svg .lb-port:hover,.lb-svg .lb-port.pending{fill:var(--lb-accent);stroke-width:4}.lb-svg .lb-edge{fill:none;stroke:var(--lb-accent);stroke-width:2;cursor:pointer;pointer-events:stroke}.lb-svg .lb-hit{stroke:transparent;stroke-width:16;fill:none;cursor:pointer;pointer-events:stroke}
.lb-svg .lb-edge.selected{stroke-width:4}.lb-svg .lb-header{cursor:grab}.lb-svg .lb-header:active{cursor:grabbing}.lb-svg .lb-card.selected{stroke:var(--lb-accent);stroke-width:3}.lb-svg .lb-rule{stroke:var(--lb-border);opacity:.4}
.lb-status{margin-left:auto;font-size:12px}.lb-selection{overflow-wrap:anywhere}.lb-label{flex:1;max-width:450px}.lb-hint{font-size:12px;opacity:.75;margin:4px 0 12px}
.lb-root:fullscreen{padding:20px;box-sizing:border-box;background:var(--lb-bg);overflow:auto}.lb-root:fullscreen .lb-svg{height:calc(100dvh - 200px)}
@media(max-width:650px){.lb-layout{grid-template-columns:1fr}.lb-palette{max-height:160px;border-right:0;border-bottom:1px solid var(--lb-border)}.lb-tables{display:flex;gap:8px}.lb-tables button{min-width:150px}.lb-svg{height:500px}.lb-status{margin-left:0}}
"""

JS = r"""
function mountBuilder(parent, data, changed) {
 const root=parent.querySelector('.lb-root'); if(!root)return;
 const svg=root.querySelector('.lb-svg'), ns='http://www.w3.org/2000/svg';
 let s=root._builder;
 if(!s){s=root._builder={view:[0,0,1200,700],revision:-1,selected:null,pending:null,drag:null};}
 if(s.revision!==data.document.revision || data.error){
  s.doc=JSON.parse(JSON.stringify(data.document));s.revision=data.document.revision;s.saving=false;s.pending=null;s.selected=null;
 }
 const doc=s.doc, editable=!!changed;
 const status=root.querySelector('.lb-status');
 const message=text=>{status.textContent=text;};
 const visible=()=>doc.tables.filter(t=>t.position);
 const table=id=>doc.tables.find(t=>t.id===id);
 const height=t=>68+Math.max(1,t.columns.length)*30;
 const width=420;
 const short=(v,n)=>v.length>n?v.slice(0,n-1)+'…':v;
 function node(tag,attrs={},text=null,parentNode=null){
  const el=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))el.setAttribute(k,String(v));
  if(text!==null)el.textContent=text;if(parentNode)parentNode.append(el);return el;
 }
 function send(){
  if(!editable)return;
  s.saving=true;message('Saving…');
  changed(JSON.parse(JSON.stringify(doc)));
 }
 function view(){svg.setAttribute('viewBox',s.view.join(' '));}
 function point(e){const p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;return p.matrixTransform(svg.getScreenCTM().inverse());}
 function fit(){
  const tables=visible();if(!tables.length){s.view=[0,0,1200,700];view();return;}
  const x=Math.min(...tables.map(t=>t.position.x)),y=Math.min(...tables.map(t=>t.position.y));
  const right=Math.max(...tables.map(t=>t.position.x+width)),bottom=Math.max(...tables.map(t=>t.position.y+height(t)));
  s.view=[x-60,y-60,right-x+120,Math.max(400,bottom-y+120)];view();
 }
 function endpoint(tid,cid,out){const t=table(tid);return {x:t.position.x+(out?width:0),y:t.position.y+83+t.columns.findIndex(c=>c.id===cid)*30};}
 function path(a,b){const bend=Math.max(65,Math.abs(b.x-a.x)*.45);return `M${a.x},${a.y} C${a.x+bend},${a.y} ${b.x-bend},${b.y} ${b.x},${b.y}`;}
 function drawEdges(){
  const group=svg.querySelector('.lb-edges');if(!group)return;group.replaceChildren();
  for(const e of doc.links){
   if(!table(e.source_table)?.position||!table(e.target_table)?.position)continue;
   const a=endpoint(e.source_table,e.source_column,true),b=endpoint(e.target_table,e.target_column,false),d=path(a,b);
   node('path',{d,class:'lb-hit','data-edge':e.id},null,group);
   node('path',{d,class:'lb-edge'+(s.selected?.id===e.id?' selected':''),'marker-end':'url(#lb-arrow)','data-edge':e.id,tabindex:0,role:'button','aria-label':`${table(e.source_table).name} to ${table(e.target_table).name}: ${e.label||'relationship'}`},null,group);
   if(e.label){const label=node('text',{x:(a.x+b.x)/2,y:(a.y+b.y)/2-10,'text-anchor':'middle','font-size':12,'data-edge':e.id},short(e.label,45),group);node('title',{},e.label,label);}
  }
 }
 function inspector(){
  const e=s.selected?.kind==='edge'?doc.links.find(e=>e.id===s.selected.id):null,t=s.selected?.kind==='table'?table(s.selected.id):null;
  root.querySelector('.lb-selection').textContent=e?`${table(e.source_table).name} → ${table(e.target_table).name}`:t?t.name:'Select a table or relationship.';
  const input=root.querySelector('.lb-label');input.hidden=!e||!editable;input.value=e?.label||'';
  root.querySelector('[data-action=label]').hidden=!e||!editable;
  const remove=root.querySelector('[data-action=remove]');remove.hidden=!s.selected||!editable;remove.textContent=t?'Remove from canvas':'Delete relationship';
 }
 function draw(){
  svg.replaceChildren();const defs=node('defs',{},null,svg);
  const marker=node('marker',{id:'lb-arrow',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:7,markerHeight:7,orient:'auto-start-reverse'},null,defs);
  node('path',{d:'M0 0L10 5L0 10z',fill:'var(--lb-accent)'},null,marker);
  node('g',{class:'lb-edges'},null,svg);
  if(!visible().length)node('text',{x:80,y:160,'font-size':20},editable?'Add tables from the catalog to start your lineage.':'No tables placed on this canvas.',svg);
  for(const t of visible()){
   const g=node('g',{'data-table':t.id,transform:`translate(${t.position.x},${t.position.y})`},null,svg);
   node('rect',{width,height:height(t),rx:7,class:'lb-card'+(s.selected?.id===t.id?' selected':'')},null,g);
   const color={source:'#208b79',intermediate:'#bc872e',target:'#477fc4'}[t.role];
   node('rect',{x:0,y:8,width:4,height:46,fill:color},null,g);
   const header=node('g',{class:'lb-header',tabindex:0,role:'button','aria-label':`${t.name}, ${t.role}. Arrow keys move this table.`},null,g);
   node('rect',{width,height:62,fill:'transparent'},null,header);
   const name=node('text',{x:16,y:25,'font-weight':600,'font-size':15},short(t.name,45),header);node('title',{},t.name+(t.comment?' — '+t.comment:''),name);
   node('text',{x:16,y:47,'font-size':11},`${t.role} · ${t.columns.length} columns`,header);
   node('line',{x1:0,x2:width,y1:62,y2:62,class:'lb-rule'},null,g);
   for(const [i,c]of t.columns.entries()){
    const y=83+i*30;
    for(const [x,value,n]of [[16,c.name,20],[176,c.data_type,16],[276,c.comment,19]]){const tx=node('text',{x,y:y+4,'font-size':12},short(value,n),g);node('title',{},value,tx);}
    node('line',{x1:10,x2:width-10,y1:y+14,y2:y+14,class:'lb-rule'},null,g);
    if(editable)for(const out of [false,true]){const port=node('circle',{cx:out?width:0,cy:y,r:6,class:'lb-port'+(s.pending?.table===t.id&&s.pending?.column===c.id&&out?' pending':''),'data-port':out?'out':'in','data-column':c.id,tabindex:0,role:'button','aria-label':`${out?'Output from':'Input to'} ${t.name}.${c.name}`},null,g);node('title',{},`${out?'Connect from':'Connect to'} ${c.name}`,port);}
   }
   if(!t.columns.length)node('text',{x:16,y:88,'font-size':12},'Add columns in the schema editor.',g);
  }
  drawEdges();view();inspector();
 }
 function select(kind,id){s.selected={kind,id};draw();}
 function connect(tid,cid){
  const p=s.pending;if(!p)return;
  if(p.table===tid&&p.column===cid){message('Choose a different target column.');return;}
  if(doc.links.some(e=>e.source_table===p.table&&e.source_column===p.column&&e.target_table===tid&&e.target_column===cid)){message('This relationship already exists.');return;}
  if(doc.links.length>=2000){message('The builder supports up to 2,000 relationships.');return;}
  doc.links.push({id:crypto.randomUUID(),source_table:p.table,source_column:p.column,target_table:tid,target_column:cid,label:''});s.pending=null;draw();send();
 }
 function add(id,pos){
  if(s.saving||!editable)return;const t=table(id);if(t.position){select('table',id);return;}
  t.position={x:Math.min(12000,Math.max(0,pos?.x??s.view[0]+80)),y:Math.min(12000,Math.max(0,pos?.y??s.view[1]+80))};draw();send();
 }
 function palette(){
  const filter=root.querySelector('.lb-search').value.toLowerCase(),list=root.querySelector('.lb-tables');list.replaceChildren();
  for(const t of doc.tables.filter(t=>t.name.toLowerCase().includes(filter))){
   const b=document.createElement('button');b.type='button';b.textContent=t.name;b.draggable=editable&&!t.position;
   const detail=document.createElement('small');detail.textContent=`${t.role} · ${t.columns.length} columns${t.position?' · on canvas':''}`;b.append(detail);
   b.onclick=()=>add(t.id);b.ondragstart=e=>e.dataTransfer.setData('text/plain',t.id);list.append(b);
  }
 }
 svg.ondragover=e=>{if(editable)e.preventDefault();};svg.ondrop=e=>{e.preventDefault();const id=e.dataTransfer.getData('text/plain');if(table(id))add(id,point(e));};
 svg.onpointerdown=e=>{
  if(e.button!==0||s.saving)return;const port=e.target.closest('[data-port]'),card=e.target.closest('[data-table]'),edge=e.target.closest('[data-edge]');
  if(port&&editable){e.preventDefault();if(port.dataset.port==='out'){s.pending={table:card.dataset.table,column:port.dataset.column};s.drag={kind:'link'};message('Choose or drag to a left input port.');draw();}else connect(card.dataset.table,port.dataset.column);return;}
  if(edge){select('edge',edge.dataset.edge);return;}
  if(card){s.selected={kind:'table',id:card.dataset.table};inspector();if(!e.target.closest('.lb-header')||!editable)return;
   const t=table(card.dataset.table),p=point(e);s.drag={kind:'table',id:t.id,x:p.x,y:p.y,start:{...t.position},moved:false};
  }else{s.drag={kind:'pan',x:e.clientX,y:e.clientY,start:[...s.view]};s.pending=null;}
  svg.setPointerCapture(e.pointerId);
 };
 svg.onpointermove=e=>{
  const d=s.drag;if(!d)return;
  if(d.kind==='pan'){const box=svg.getBoundingClientRect();const scale=Math.max(s.view[2]/box.width,s.view[3]/box.height);s.view=[d.start[0]-(e.clientX-d.x)*scale,d.start[1]-(e.clientY-d.y)*scale,s.view[2],s.view[3]];view();}
  if(d.kind==='table'){const p=point(e),t=table(d.id);t.position={x:Math.max(0,Math.min(12000,d.start.x+p.x-d.x)),y:Math.max(0,Math.min(12000,d.start.y+p.y-d.y))};d.moved=true;
   for(const el of svg.querySelectorAll('[data-table]'))if(el.dataset.table===t.id)el.setAttribute('transform',`translate(${t.position.x},${t.position.y})`);drawEdges();}
  if(d.kind==='link'){let ghost=svg.querySelector('.lb-ghost');if(!ghost)ghost=node('path',{class:'lb-ghost',fill:'none',stroke:'var(--lb-accent)','stroke-dasharray':'5 4','pointer-events':'none'},null,svg);ghost.setAttribute('d',path(endpoint(s.pending.table,s.pending.column,true),point(e)));}
 };
 svg.onpointerup=e=>{
  const d=s.drag;s.drag=null;if(!d)return;
  if(svg.hasPointerCapture(e.pointerId))svg.releasePointerCapture(e.pointerId);
  if(d.kind==='link'){const port=e.target.closest('[data-port=in]');if(port)connect(port.closest('[data-table]').dataset.table,port.dataset.column);else draw();}
  if(d.kind==='table'&&d.moved){draw();send();}
 };
 svg.onpointercancel=()=>{if(s.drag?.kind==='table')table(s.drag.id).position=s.drag.start;s.drag=null;s.pending=null;draw();};
 svg.onkeydown=e=>{
  if(e.key==='Escape'){s.pending=null;s.drag=null;draw();return;}
  if(s.saving)return;const port=e.target.closest('[data-port]'),card=e.target.closest('[data-table]'),edge=e.target.closest('[data-edge]');
  if((e.key==='Enter'||e.key===' ')&&(port||edge||card)){e.preventDefault();if(port){if(port.dataset.port==='out'){s.pending={table:card.dataset.table,column:port.dataset.column};message('Choose a target input port.');}else connect(card.dataset.table,port.dataset.column);}else select(edge?'edge':'table',edge?.dataset.edge||card.dataset.table);}
  if(editable&&card&&e.target.closest('.lb-header')&&['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();const t=table(card.dataset.table),step=e.shiftKey?50:10;t.position.x=Math.min(12000,Math.max(0,t.position.x+(e.key==='ArrowRight'?step:e.key==='ArrowLeft'?-step:0)));t.position.y=Math.min(12000,Math.max(0,t.position.y+(e.key==='ArrowDown'?step:e.key==='ArrowUp'?-step:0)));draw();send();}
 };
 svg.onwheel=e=>{e.preventDefault();const p=point(e),factor=e.deltaY>0?1.12:.89;zoom(factor,p);};
 function zoom(factor,p){const w=s.view[2]*factor;if(w<160||w>30000)return;p=p||{x:s.view[0]+s.view[2]/2,y:s.view[1]+s.view[3]/2};s.view=[p.x-(p.x-s.view[0])*factor,p.y-(p.y-s.view[1])*factor,w,s.view[3]*factor];view();}
 function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),3000);}
 function image(format){
  if(!visible().length){message('Place a table on the canvas before exporting an image.');return;}
  const tables=visible(),x=Math.min(...tables.map(t=>t.position.x))-40,y=Math.min(...tables.map(t=>t.position.y))-40;
  const w=Math.max(...tables.map(t=>t.position.x+width))-x+40,h=Math.max(...tables.map(t=>t.position.y+height(t)))-y+40;
  const clone=svg.cloneNode(true);clone.setAttribute('xmlns',ns);clone.setAttribute('viewBox',`${x} ${y} ${w} ${h}`);clone.setAttribute('width',w);clone.setAttribute('height',h);
  const style=getComputedStyle(root),color=style.color,bg=style.getPropertyValue('--lb-bg').trim()||'#fff',accent=style.getPropertyValue('--lb-accent').trim()||'#176db1',border=style.getPropertyValue('--lb-border').trim()||'#a3afbd',card=style.getPropertyValue('--lb-card').trim()||'#f2f5f9';
  clone.querySelectorAll('.lb-port,.lb-hit,.lb-ghost').forEach(n=>n.remove());
  const css=node('style',{},`.lb-card{fill:${card};stroke:${border}}text{fill:${color};font-family:Arial,sans-serif}.lb-edge{fill:none;stroke:${accent};stroke-width:2}.lb-rule{stroke:${border};opacity:.4}`,null);clone.prepend(css);
  clone.querySelectorAll('[fill="var(--lb-accent)"]').forEach(n=>n.setAttribute('fill',accent));
  clone.prepend(node('rect',{x,y,width:w,height:h,fill:bg}));
  const xml=new XMLSerializer().serializeToString(clone),blob=new Blob([xml],{type:'image/svg+xml;charset=utf-8'});
  if(format==='svg'){download(blob,'lineage-builder.svg');message('SVG exported.');return;}
  if(w*h>16000000||w>8192||h>8192){message('PNG exceeds 16 million pixels or 8,192px per side. Use SVG or bring tables closer together.');return;}
  const url=URL.createObjectURL(blob),img=new Image();img.onload=()=>{try{const c=document.createElement('canvas');c.width=Math.ceil(w);c.height=Math.ceil(h);c.getContext('2d').drawImage(img,0,0);c.toBlob(b=>{if(b){download(b,'lineage-builder.png');message('PNG exported.');}},'image/png');}catch(_){message('PNG export failed. Try SVG.');}finally{URL.revokeObjectURL(url);}};img.onerror=()=>{URL.revokeObjectURL(url);message('PNG export failed. Try SVG.');};img.src=url;
 }
 root.querySelector('.lb-search').oninput=palette;
 root.querySelectorAll('[data-action]').forEach(button=>{button.onclick=()=>{
  const action=button.dataset.action;
  if(action==='fit')fit();if(action==='in')zoom(.8);if(action==='out')zoom(1.25);
  if(action==='full'){if(document.fullscreenElement)document.exitFullscreen();else root.requestFullscreen?.().catch(()=>message('Full screen is unavailable.'));}
  if(action==='svg'||action==='png')image(action);
  if(!editable||s.saving)return;
  if(action==='label'&&s.selected?.kind==='edge'){doc.links.find(e=>e.id===s.selected.id).label=root.querySelector('.lb-label').value;draw();send();}
  if(action==='remove'&&s.selected){if(s.selected.kind==='edge')doc.links=doc.links.filter(e=>e.id!==s.selected.id);else table(s.selected.id).position=null;s.selected=null;draw();palette();send();}
 };});
 root.querySelector('.lb-palette').hidden=!editable;
 root.querySelector('.lb-layout').style.gridTemplateColumns=editable?'':'1fr';
 root.querySelector('.lb-hint').textContent=editable?'Add tables from the catalog. Drag headers to move. Drag right column ports to left ports, or select the two ports in order. Drag empty space to pan; scroll to zoom. Edits save automatically.':'Drag empty space to pan, scroll to zoom, or use Fit diagram. Authored lineage presentation.';
 draw();palette();message(data.error|| (s.saving?'Saving…':editable?'All changes saved':'Authored lineage'));
 if(!s.initialFit){fit();s.initialFit=true;}
}
"""

_CANVAS = st.components.v2.component("dataforge_lineage_builder", html=BODY, css=CSS,
    js=JS + "\nexport default function(c){mountBuilder(c.parentElement,c.data,v=>c.setTriggerValue('edit',v));}\n")


def canvas(document: BuilderDocument, key: str, on_edit, error: str = ""):
    return _CANVAS(data={"document": document.model_dump(), "error": error}, key=key,
                   on_edit_change=on_edit, height="content")


def builder_html(document: BuilderDocument) -> bytes:
    """Export a fully offline interactive presentation with inert imported text."""
    payload = json.dumps({"document": document.model_dump()}).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>GraveTrail · Authored lineage</title><style>body{margin:24px;font-family:Arial,sans-serif}"
            + CSS + "</style></head><body><h1>Authored lineage</h1>" + BODY + "<script>" + JS
            + "\nmountBuilder(document," + payload + ",null);</script></body></html>").encode()
