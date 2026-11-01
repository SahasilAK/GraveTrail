"""Offline SVG authoring canvas; the same renderer powers HTML presentations."""
import json

import streamlit as st

from dataforge.datatypes import TYPE_CATALOG
from dataforge.lineage_builder import BuilderDocument
from dataforge.theme_configuration import PALETTES


def builder_node_colors(theme: str | None, palette: str = "semantic", *, dark: bool = True) -> dict:
    """Use the existing lineage palette's role colors and 25% role/graph fill blend."""
    colors = PALETTES.get(theme, {})
    if colors:
        def blend(role: str) -> str:
            return "#" + "".join(f"{round(int(colors[role][i:i+2], 16)*.25 + int(colors['graph'][i:i+2], 16)*.75):02x}"
                                  for i in (1, 3, 5))
        return {role: {"fill": blend(role) if palette == "semantic" else colors["surface"],
                       "stroke": colors[role] if palette == "semantic" else colors["border"], "text": colors["text"]}
                for role in ("source", "intermediate", "target")}
    fills = ["#203f3d", "#3b3354", "#273d58"] if dark else ["#e0efeb", "#ece7f7", "#e3ecfb"]
    return {role: {"fill": fill if palette == "semantic" else ("#303b48" if dark else "#edf0f4"),
                   "stroke": "#7489a3" if dark else "#8d9cb1", "text": "#edf2f9" if dark else "#23334a"}
            for role, fill in zip(("source", "intermediate", "target"), fills)}

COLUMN_BODY = """
<div class="lb-columns">
 <datalist id="lb-types"></datalist>
 <div class="lb-column-scroll"><table><thead><tr><th>Column name</th><th>Data type</th><th>Precision</th><th>Scale</th><th>Comment</th><th></th></tr></thead><tbody></tbody></table></div>
 <button type="button" class="lb-add-column">Add column</button>
</div>
"""

BODY = """
<div class="lb-root">
 <div class="lb-toolbar">
  <button data-action="undo" title="Undo (Ctrl+Z)" aria-keyshortcuts="Control+Z">Undo</button>
  <button data-action="redo" title="Redo (Ctrl+Y)" aria-keyshortcuts="Control+Y">Redo</button>
  <label class="lb-tool-options">Tool <select class="lb-tool" aria-label="Canvas tool"><option value="select">Select tables</option><option value="pan">Pan</option></select></label>
  <button data-action="fit">Fit diagram</button><button data-action="out" aria-label="Zoom out">−</button>
  <button data-action="in" aria-label="Zoom in">+</button><button data-action="full">Full screen</button>
  <button data-action="save-work">Save canvas</button><button data-action="clear-canvas">Clear canvas</button>
  <button data-action="export" aria-haspopup="menu" aria-expanded="false" aria-controls="lb-context">Export ▾</button>
  <label class="lb-connection-options">Connection <select class="lb-mode" aria-label="Connection type"><option value="lineage">Lineage</option><option value="join">Join</option></select></label>
  <label class="lb-join-options" hidden>Join type <select class="lb-join-type" aria-label="Join type"><option>Inner join</option><option>Left join</option><option>Right join</option><option>Full outer join</option><option>Cross join</option><option>Self join</option><option value="__custom__">Custom…</option></select></label>
  <input class="lb-custom-join" aria-label="Custom join type" maxlength="100" placeholder="Custom join type" hidden>
  <span class="lb-status" role="status" aria-live="polite"></span>
 </div>
 <div class="lb-layout">
  <aside class="lb-palette"><label>Table catalog<input class="lb-search" placeholder="Find a table" aria-label="Find a table"></label>
   <div class="lb-catalog-actions"><button data-action="create">Create table</button><button data-action="add">Add table</button><button data-action="folder">New folder</button></div><div class="lb-tables"></div></aside>
  <div class="lb-board"><svg class="lb-svg" tabindex="0" role="group" aria-label="Lineage canvas. Drag table headers to move. Connect an output port to an input port." viewBox="0 0 1200 700" preserveAspectRatio="xMidYMin meet"></svg></div>
 </div>
 <div class="lb-inspector"><span class="lb-selection">Select a table or relationship.</span>
  <button data-action="color" hidden>Set trace color</button><button data-action="clear-color" hidden>Clear assigned color</button>
  <span class="lb-trace-summary" aria-live="polite"></span>
  <input class="lb-label" aria-label="Relationship label" placeholder="Relationship label, e.g. Join" maxlength="500" hidden>
  <button data-action="label" hidden>Apply label</button><button data-action="remove" hidden>Remove</button>
 </div>
 <p class="lb-hint">Add a table from the catalog. Drag its header to move it. Drag a right column port to a left port, or select the two ports in order. Drag empty space to pan; scroll to zoom. Edits save automatically.</p>
 <dialog class="lb-create" aria-labelledby="lb-create-title">
  <form class="lb-create-form">
   <h2 id="lb-create-title">Create table</h2>
   <div class="lb-create-meta">
    <label>Table name<input name="table_name" required maxlength="300" placeholder="e.g. mart.customer_orders"></label>
    <label>Table role<select name="role"><option value="source">Source</option><option value="intermediate" selected>Intermediate</option><option value="target">Target</option></select></label>
    <label>System / database<select name="system" required></select></label>
    <label class="lb-custom-system" hidden>Custom system<input name="custom_system" maxlength="100" placeholder="System name"></label>
    <label>Table comment<input name="comment" maxlength="2000"></label>
   </div>
   <p>Type or choose a datatype. Lengths and decimal precision/scale are optional: VARCHAR, VARCHAR(200), DECIMAL or DECIMAL(18,2). Custom types are welcome.</p>
   <!--column-editor-->
   <p class="lb-create-error" role="alert"></p>
   <div class="lb-create-actions"><button type="button" class="lb-cancel-create">Cancel</button><button type="submit">Create table</button></div>
  </form>
 </dialog>
 <dialog class="lb-add" aria-labelledby="lb-add-title">
  <h2 id="lb-add-title">Add a table to the catalog</h2>
  <label>Find a schema table<input class="lb-add-search" aria-label="Find a schema table" placeholder="Search all table schemas"></label>
  <div class="lb-add-list"></div><button type="button" class="lb-close-add">Close</button>
 </dialog>
 <dialog class="lb-folder-dialog" aria-label="New catalog folder"><form class="lb-folder-form">
  <h2>New folder</h2><label>Folder name<input name="folder_name" required maxlength="300"></label>
  <p class="lb-folder-error" role="alert"></p><button type="button" class="lb-folder-cancel">Cancel</button><button type="submit">Create folder</button>
 </form></dialog>
 <dialog class="lb-color-dialog" aria-label="Trace color"><form class="lb-color-form">
  <h2>Trace color</h2><p class="lb-color-targets"></p>
  <label>Custom color <input type="color" class="lb-color-picker" aria-label="Custom trace color" value="#2563eb"></label>
  <div class="lb-color-swatches" aria-label="Trace color presets"></div>
  <p>The color follows downstream lineage. Shared paths show all contributing colors.</p>
  <button type="button" class="lb-color-cancel">Cancel</button><button type="button" class="lb-color-clear">Clear assigned color</button><button type="submit">Apply color</button>
 </form></dialog>
 <dialog class="lb-work-dialog" aria-labelledby="lb-work-title"><form class="lb-work-form">
  <h2 id="lb-work-title">Save canvas</h2><p class="lb-work-description"></p>
  <label class="lb-work-mode" hidden>Save option<select name="save_mode" aria-label="Save option"><option value="overwrite">Overwrite saved work</option><option value="new">Save as new work</option></select></label>
  <label>Work name (optional)<input name="work_name" maxlength="300" placeholder="Leave blank for an automatic name"></label>
  <p class="lb-work-error" role="alert"></p><button type="button" class="lb-work-cancel">Cancel</button><button type="submit" class="lb-work-submit">Save canvas</button><button type="button" class="lb-work-overwrite" hidden>Overwrite saved work</button>
 </form></dialog>
 <div id="lb-context" class="lb-context" role="menu" aria-label="Lineage options" tabindex="-1" hidden></div>
</div>
""".replace("<!--column-editor-->", COLUMN_BODY)

CSS = """
.lb-root{font:14px/1.5 var(--st-font,sans-serif);color:var(--st-text-color,#243449);--lb-bg:var(--st-background-color,#fff);--lb-card:var(--st-secondary-background-color,#f2f5f9);--lb-border:var(--st-border-color,#a3afbd);--lb-accent:var(--st-primary-color,#176db1)}
.lb-toolbar,.lb-inspector{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:10px 0}
.lb-root button,.lb-root input,.lb-root select{font:inherit;color:inherit;background:var(--lb-bg);border:1px solid var(--lb-border);border-radius:5px;padding:7px 10px;min-height:36px;box-sizing:border-box}
.lb-root button{cursor:pointer}.lb-root button:disabled{opacity:.5;cursor:wait}.lb-root button:hover{border-color:var(--lb-accent)}
.lb-root [hidden]{display:none!important}
.lb-root :is(button,input,svg,[tabindex]):focus-visible{outline:2px solid var(--lb-accent);outline-offset:3px}
.lb-layout{display:grid;grid-template-columns:220px minmax(0,1fr);grid-template-rows:minmax(0,1fr);border:1px solid var(--lb-border);border-radius:8px;overflow:hidden}
.lb-palette{padding:12px;background:var(--lb-card);border-right:1px solid var(--lb-border);height:620px;box-sizing:border-box;display:flex;flex-direction:column;min-height:0;overflow:hidden}
.lb-tables{flex:1;min-height:0;overflow-y:auto;scrollbar-gutter:stable}
.lb-search{display:block;width:100%;margin:8px 0 12px}.lb-tables button{display:block;text-align:left;width:100%;margin:7px 0;overflow-wrap:anywhere}.lb-tables small{display:block;opacity:.7}
.lb-catalog-actions{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:10px}.lb-catalog-actions button{font-size:12px;padding:5px 7px}.lb-folder{border:1px solid var(--lb-border);border-radius:5px;margin:8px 0;padding:6px}.lb-folder summary{cursor:pointer;overflow-wrap:anywhere}.lb-folder-drop{min-height:30px;padding:5px}.lb-folder-drop p{font-size:12px;opacity:.7}.lb-drop-hover{outline:2px dashed var(--lb-accent)}
.lb-tables button{touch-action:none}.lb-catalog-ghost{position:fixed;z-index:10;pointer-events:none;background:var(--lb-card);border:1px solid var(--lb-accent);border-radius:5px;padding:8px;max-width:220px;overflow-wrap:anywhere}
.lb-board{min-width:0;overflow:hidden;background:var(--lb-bg)}.lb-svg{display:block;width:100%;height:620px;touch-action:none;background-image:radial-gradient(var(--lb-border) .6px,transparent .6px);background-size:20px 20px}
.lb-svg .lb-card{fill:var(--lb-card);stroke:var(--lb-border)}.lb-svg text{fill:var(--st-text-color,#243449);user-select:none}.lb-svg .lb-port{fill:var(--lb-bg);stroke:var(--lb-accent);stroke-width:2;cursor:crosshair}
.lb-svg .lb-port:hover,.lb-svg .lb-port.pending{fill:var(--lb-accent);stroke-width:4}.lb-svg .lb-edge{fill:none;stroke:var(--lb-accent);stroke-width:2;cursor:pointer;pointer-events:stroke}.lb-svg .lb-hit{stroke:transparent;stroke-width:16;fill:none;cursor:pointer;pointer-events:stroke}
.lb-svg .lb-edge.lb-join{stroke:#d89e3a;stroke-dasharray:6 4}
.lb-svg .lb-edge.selected{stroke-width:4}.lb-svg .lb-header{cursor:grab}.lb-svg .lb-header:active{cursor:grabbing}.lb-svg .lb-card.selected{stroke:var(--lb-accent);stroke-width:3}.lb-svg .lb-rule{stroke:var(--lb-rule,var(--lb-border));stroke-width:1;opacity:.75}
.lb-svg .lb-resize{fill:transparent;pointer-events:all}.lb-svg .lb-expand{cursor:pointer}.lb-svg .lb-expand:hover rect{fill:#ffffff20}
.lb-svg .lb-marquee{fill:var(--lb-accent);fill-opacity:.12;stroke:var(--lb-accent);stroke-dasharray:5 3;pointer-events:none}
.lb-alt-pan .lb-svg,.lb-alt-pan .lb-svg *{cursor:grab!important}.lb-alt-pan.lb-pan-dragging .lb-svg,.lb-alt-pan.lb-pan-dragging .lb-svg *{cursor:grabbing!important}
.lb-context{position:fixed;z-index:30;min-width:210px;max-width:min(310px,90vw);max-height:70dvh;overflow:auto;padding:5px;background:var(--lb-card);border:1px solid var(--lb-border);border-radius:7px;box-shadow:0 8px 24px #0005}.lb-context button{display:block;text-align:left;width:100%;background:transparent;border:0;white-space:normal;overflow-wrap:anywhere}.lb-context button:disabled{cursor:default}.lb-context button:hover:not(:disabled),.lb-context button:focus-visible{background:var(--lb-bg)}.lb-context hr{border:0;border-top:1px solid var(--lb-border);margin:4px}
.lb-color-dialog{color:inherit;background:var(--lb-bg);border:1px solid var(--lb-border);border-radius:8px;width:min(460px,90vw);padding:24px}.lb-color-dialog::backdrop{background:#0008}.lb-color-picker{width:65px;vertical-align:middle}.lb-color-swatches{display:flex;gap:8px;margin:18px 0;flex-wrap:wrap}.lb-color-swatches button{width:36px;padding:0;min-height:36px}.lb-trace-summary{font-size:12px;opacity:.8}
.lb-status{margin-left:auto;font-size:12px}.lb-selection{overflow-wrap:anywhere}.lb-label{flex:1;max-width:450px}.lb-hint{font-size:12px;opacity:.75;margin:4px 0 12px}
.lb-root:fullscreen{padding:20px;box-sizing:border-box;background:var(--lb-bg);overflow:auto;display:flex;flex-direction:column}.lb-root:fullscreen .lb-layout{flex:1;height:0;min-height:200px}.lb-root:fullscreen .lb-svg{height:100%}.lb-root:fullscreen .lb-palette{height:100%}
.lb-create{color:inherit;background:var(--lb-bg);border:1px solid var(--lb-border);border-radius:8px;width:min(1000px,90vw);max-height:85dvh;box-sizing:border-box;padding:24px}.lb-create::backdrop{background:#0008}
.lb-add,.lb-folder-dialog,.lb-work-dialog{color:inherit;background:var(--lb-bg);border:1px solid var(--lb-border);border-radius:8px;width:min(540px,90vw);padding:24px}.lb-add::backdrop,.lb-folder-dialog::backdrop,.lb-work-dialog::backdrop{background:#0008}.lb-add-search{width:100%;margin:8px 0}.lb-add-list{max-height:350px;overflow-y:auto;margin:12px 0}.lb-add-list button{display:block;width:100%;text-align:left;margin:6px 0}.lb-folder-dialog input,.lb-work-dialog input{width:100%;margin:8px 0}
.lb-work-dialog label{display:block;margin:12px 0}.lb-work-mode select{margin-left:8px}
.lb-create h2{margin:0 0 16px}.lb-create-meta{display:grid;grid-template-columns:1fr 1fr;gap:12px}.lb-create label{display:flex;flex-direction:column;gap:4px}.lb-create p{font-size:13px}.lb-column-scroll{overflow:auto;margin:16px 0}.lb-columns table{border-collapse:collapse;width:100%}.lb-columns th{text-align:left;font-size:12px;padding:4px}.lb-columns td{padding:4px}.lb-columns td input{width:100%;min-width:130px}.lb-columns td input[type=number]{min-width:80px}.lb-create-actions{display:flex;justify-content:flex-end;gap:8px}.lb-create-error{color:var(--st-red-color,#c74747)}
@media(max-width:650px){.lb-layout{grid-template-columns:1fr;grid-template-rows:auto auto}.lb-palette{height:160px;border-right:0;border-bottom:1px solid var(--lb-border)}.lb-svg{height:500px}.lb-status{margin-left:0}.lb-create-meta{grid-template-columns:1fr}}
"""

COLUMN_JS = r"""
function mountColumns(parent, rows, options, changed=null){
 const body=parent.querySelector('tbody'),types=parent.querySelector('#lb-types'),addButton=parent.querySelector('.lb-add-column');
 const state=parent._columns||(parent._columns={next:0,ready:false});state.changed=changed;
 function read(){return Array.from(body.children,row=>({id:row.dataset.id||'',...Object.fromEntries(Array.from(row.querySelectorAll('input'),input=>[input.dataset.field,input.type==='number'?(input.value===''?null:Number(input.value)):input.value]))}));}
 function emit(){if(state.changed)state.changed(read());}
 function add(value={},notify=true){
  if(body.children.length>=200)return;
  const row=document.createElement('tr'),index=++state.next;row.dataset.id=value.id||'';
  for(const [key,label,kind]of [['name','Column name','text'],['data_type','Data type','text'],['precision','Precision','number'],['scale','Scale','number'],['comment','Comment','text']]){
   const td=document.createElement('td'),input=document.createElement('input');input.type=kind;input.dataset.field=key;input.setAttribute('aria-label',`${label} ${index}`);input.value=value[key]??'';
   if(key==='name'){input.required=true;input.maxLength=300;}
   if(key==='data_type'){input.setAttribute('list','lb-types');input.maxLength=300;input.placeholder='Type or choose';}
   if(key==='precision'){input.min='1';input.step='1';input.placeholder='e.g. 18';}
   if(key==='scale'){input.step='1';input.placeholder='0';}
   if(key==='comment')input.maxLength=2000;
   input.oninput=emit;td.append(input);row.append(td);
  }
  const td=document.createElement('td'),remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label',`Remove column ${index}`);remove.onclick=()=>{row.remove();emit();};td.append(remove);row.append(td);body.append(row);if(notify)emit();
 }
 function setOptions(values){types.replaceChildren();for(const name of values){const option=document.createElement('option');option.value=name;types.append(option);}}
 function reset(){body.replaceChildren();state.next=0;add({},false);}
 if(!state.ready){for(const row of rows)add(row,false);if(!rows.length)add({},false);state.ready=true;}
 addButton.onclick=()=>add();setOptions(options);
 return {read,setOptions,reset};
}
"""

TRACE_JS = r"""
function lineageTraces(document, selected=[]){
 const tables=new Map(document.tables.map(t=>[t.id,t])),outgoing=new Map(),joins=[];
 for(const link of document.links){
  if(!tables.has(link.source_table)||!tables.has(link.target_table))continue;
  if(link.kind==='join'){joins.push(link);continue;}
  if(!outgoing.has(link.source_table))outgoing.set(link.source_table,[]);outgoing.get(link.source_table).push(link);
 }
 function downstream(roots){
  const reached=new Set(roots.filter(id=>tables.has(id))),links=new Set(),queue=[...reached];
  for(let i=0;i<queue.length;i++)for(const link of outgoing.get(queue[i])||[]){links.add(link.id);if(!reached.has(link.target_table)){reached.add(link.target_table);queue.push(link.target_table);}}
  for(const link of joins)if(reached.has(link.source_table)||reached.has(link.target_table))links.add(link.id);
  return {tables:reached,links};
 }
 const nodeColors=new Map(),edgeColors=new Map();
 const add=(map,id,color)=>{if(!map.has(id))map.set(id,new Set());map.get(id).add(color);};
 for(const table of document.tables)if(table.color){
  const color=table.color.toLowerCase(),trace=downstream([table.id]);
  for(const id of trace.tables)add(nodeColors,id,color);for(const id of trace.links)add(edgeColors,id,color);
 }
 return {active:selected.length>0,selected:downstream(selected),nodeColors,edgeColors};
}
"""

JS = COLUMN_JS + TRACE_JS + r"""
function mountBuilder(parent, data, changed, createTable=null, workAction=null) {
 const root=parent.querySelector('.lb-root'); if(!root)return;
 const svg=root.querySelector('.lb-svg'),contextMenu=root.querySelector('.lb-context'),exportButton=root.querySelector('[data-action=export]'),ns='http://www.w3.org/2000/svg';
 let s=root._builder;
 if(!s){s=root._builder={view:[0,0,1200,700],revision:-1,selected:null,pending:null,drag:null,undo:[],redo:[]};}
 s.undo=s.undo||[];s.redo=s.redo||[];
 s.selection=s.selection||new Set();s.openFolders=s.openFolders||new Set();
 const copy=value=>JSON.parse(JSON.stringify(value));
 function snapshot(value){return {positions:Object.fromEntries(value.tables.map(t=>[t.id,t.position?{...t.position}:null])),sizes:Object.fromEntries(value.tables.map(t=>[t.id,t.size?{...t.size}:null])),tableFolders:Object.fromEntries(value.tables.map(t=>[t.id,t.folder||null])),catalogHidden:Object.fromEntries(value.tables.map(t=>[t.id,!!t.catalog_hidden])),colors:Object.fromEntries(value.tables.map(t=>[t.id,t.color||''])),folders:copy(value.folders||[]),links:copy(value.links)};}
 const updated=s.revision!==data.document.revision;
 if(updated || data.error){
  const operation=s.operation;
  if(updated&&s.saving&&operation&&!data.error){
   if(operation.kind==='undo'){s.undo.pop();s.redo.push(operation.before);}
   else if(operation.kind==='redo'){s.redo.pop();s.undo.push(operation.before);}
   else if(operation.kind==='edit'){s.undo.push(operation.before);s.redo=[];}
   else if(operation.kind==='clear'){s.undo=[];s.redo=[];s.selection.clear();}
   s.undo=s.undo.slice(-50);s.redo=s.redo.slice(-50);
  }else if(updated&&s.revision!==-1){s.undo=[];s.redo=[];s.selection.clear();}
  s.doc=copy(data.document);s.revision=data.document.revision;s.saving=false;s.selected=null;s.operation=null;s.lastSaved=snapshot(s.doc);
  if(data.error)s.pending=null;
 }
 const workDone=!!data.work_result&&s.workResult!==data.work_result.id;
 const showWorkResult=workDone&&s.workPending;
 if(workDone){s.workResult=data.work_result.id;s.saving=false;s.operation=null;}
 const doc=s.doc, editable=!!changed;
 doc.folders=doc.folders||[];s.selection=new Set([...s.selection].filter(id=>doc.tables.some(t=>t.id===id&&t.position)));
 const tool=root.querySelector('.lb-tool');
 function setAltPan(active){
  if(active===!!s.altPan)return;
  if(active){s.previousTool=tool.value;s.altPan=true;tool.value='pan';}
  else{s.altPan=false;tool.value=s.previousTool||'select';delete s.previousTool;
   if(s.drag?.temporaryPan){const pointer=s.drag.pointerId;s.drag=null;if(svg.hasPointerCapture(pointer))svg.releasePointerCapture(pointer);}
   root.classList.remove('lb-pan-dragging');
  }
  root.classList.toggle('lb-alt-pan',active);
 }
 s.panEvents?.abort();const panEvents=new AbortController();s.panEvents=panEvents;
 window.addEventListener('keyup',e=>{if(e.key==='Alt'&&s.altPan){e.preventDefault();setAltPan(false);}},{signal:panEvents.signal});
 window.addEventListener('blur',()=>{setAltPan(false);closeMenu(false);},{signal:panEvents.signal});
 window.addEventListener('pointerdown',e=>{if(!e.composedPath().includes(contextMenu)&&!e.composedPath().includes(exportButton))closeMenu(false);},{capture:true,signal:panEvents.signal});
 window.addEventListener('resize',()=>closeMenu(false),{signal:panEvents.signal});
 root.onfocusout=e=>{if(!root.contains(e.relatedTarget))setAltPan(false);};
 const mode=root.querySelector('.lb-mode'),joinSelect=root.querySelector('.lb-join-type'),customJoin=root.querySelector('.lb-custom-join');
 function joinChoice(){return joinSelect.value==='__custom__'?(customJoin.value.trim()||'Join'):joinSelect.value;}
 function setJoinChoice(value){const known=Array.from(joinSelect.options).some(o=>o.value===value);joinSelect.value=known?value:'__custom__';customJoin.value=known?'':value;}
 function updateMode(){root.querySelector('.lb-join-options').hidden=!editable||mode.value!=='join';customJoin.hidden=!editable||mode.value!=='join'||joinSelect.value!=='__custom__';}
 if(s.pending&&!doc.tables.some(t=>t.id===s.pending.table&&t.columns.some(c=>c.id===s.pending.column)))s.pending=null;
 const status=root.querySelector('.lb-status');
 const message=text=>{status.textContent=text;};
 const visible=()=>doc.tables.filter(t=>t.position);
 const table=id=>doc.tables.find(t=>t.id===id);
 let traces,paints,arrows;
 const colorList=(map,id)=>[...(map.get(id)||[])].sort();
 function paint(colors,coordinates,owner){
  if(!colors.length)return '';if(colors.length===1)return colors[0];let entry=paints.get(owner);
  if(!entry){const id='lb-flow-'+paints.size,gradient=node('linearGradient',{id,gradientUnits:'userSpaceOnUse'},null,svg.querySelector('defs'));
   colors.forEach((color,i)=>node('stop',{offset:(i/(colors.length-1)*100)+'%','stop-color':color},null,gradient));entry={gradient,value:`url(#${id})`};paints.set(owner,entry);
  }
  const [x1,y1,x2,y2]=coordinates;for(const [key,value]of Object.entries({x1,y1,x2:x1===x2&&y1===y2?x2+1:x2,y2}))entry.gradient.setAttribute(key,value);return entry.value;
 }
 function arrow(color){
  if(arrows.has(color))return arrows.get(color);const id='lb-arrow-'+arrows.size,marker=node('marker',{id,viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:7,markerHeight:7,orient:'auto-start-reverse'},null,svg.querySelector('defs'));
  node('path',{d:'M0 0L10 5L0 10z',fill:color},null,marker);const value=`url(#${id})`;arrows.set(color,value);return value;
 }
 function tint(color){
  const fills=Object.values(data.node_colors||{}).map(c=>c.fill).filter(c=>/^#[\da-f]{6}$/i.test(c));
  const base=fills.length?[1,3,5].map(start=>fills.reduce((sum,c)=>sum+parseInt(c.slice(start,start+2),16),0)/fills.length):[255,255,255];
  return 'rgb('+[1,3,5].map((start,i)=>Math.round(parseInt(color.slice(start,start+2),16)*.22+base[i]*.78)).join(',')+')';
 }
 s.expanded=s.expanded||new Set();
 const width=t=>t.size?.width||420;
 const measure=document.createElement('canvas').getContext('2d');measure.font='12px '+getComputedStyle(svg).fontFamily;
 function wrap(value,limit){
  const lines=[];for(let text of value.split(/\r?\n/)){while(measure.measureText(text).width>limit){let low=1,high=text.length;while(low<high){const mid=Math.ceil((low+high)/2);if(measure.measureText(text.slice(0,mid)).width<=limit)low=mid;else high=mid-1;}let end=text.lastIndexOf(' ',low);if(end<=0)end=low;lines.push(text.slice(0,end));text=text.slice(end).replace(/^ /,'');}lines.push(text);}return lines;
 }
 function layout(t){
  const w=width(t),rows=t.columns.map(c=>{const expanded=s.expanded.has(c.id),lines=expanded?wrap(c.comment,w*.36-40):[c.comment];return {column:c,expanded,lines,height:expanded?Math.max(30,lines.length*16+12):30};});
  const natural=68+Math.max(30,rows.reduce((n,r)=>n+r.height,0)),h=Math.max(natural,t.size?.height||0),extra=rows.length?(h-natural)/rows.length:0;
  let y=62;for(const row of rows){row.top=y;row.height+=extra;row.center=y+row.height/2;y+=row.height;}return {width:w,height:h,rows,natural};
 }
 const height=t=>layout(t).height;
 const short=(v,n)=>v.length>n?v.slice(0,n-1)+'…':v;
 function node(tag,attrs={},text=null,parentNode=null){
  const el=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))el.setAttribute(k,String(v));
  if(text!==null)el.textContent=text;if(parentNode)parentNode.append(el);return el;
 }
 function historyButtons(){root.querySelector('[data-action=undo]').disabled=!editable||s.saving||!s.undo.length;root.querySelector('[data-action=redo]').disabled=!editable||s.saving||!s.redo.length;for(const action of ['save-work','clear-canvas'])root.querySelector(`[data-action="${action}"]`).disabled=s.saving;}
 function send(record=true){
  if(!editable)return;
  s.operation=s.operation||{kind:record?'edit':'catalog',before:s.lastSaved};s.saving=true;historyButtons();message('Saving…');
  changed(copy(doc));
 }
 function history(kind){
  if(s.saving||!editable)return;const stack=kind==='undo'?s.undo:s.redo,target=stack[stack.length-1];if(!target)return;
  s.operation={kind,before:snapshot(doc)};
  for(const t of doc.tables){t.position=target.positions[t.id]?{...target.positions[t.id]}:null;t.size=target.sizes?.[t.id]?{...target.sizes[t.id]}:null;t.folder=target.tableFolders?.[t.id]||null;t.catalog_hidden=target.catalogHidden?.[t.id]||false;t.color=target.colors?.[t.id]||'';}
  doc.folders=copy(target.folders||[]);doc.links=copy(target.links);s.pending=null;s.selected=null;s.selection.clear();draw();palette();send();svg.focus({preventScroll:true});
 }
 function removeSelected(){
  if(!editable||s.saving||(!s.selected&&!s.selection.size))return;
  if(s.selected?.kind==='edge')doc.links=doc.links.filter(e=>e.id!==s.selected.id);else for(const id of s.selection){const t=table(id);t.canvas_member=true;t.position=null;}
  s.selected=null;s.selection.clear();s.pending=null;draw();palette();send();svg.focus({preventScroll:true});
 }
 function view(){svg.setAttribute('viewBox',s.view.join(' '));}
 function point(e){const p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;return p.matrixTransform(svg.getScreenCTM().inverse());}
 function fit(){
  const tables=visible();if(!tables.length){s.view=[0,0,1200,700];view();return;}
  const x=Math.min(...tables.map(t=>t.position.x)),y=Math.min(...tables.map(t=>t.position.y));
  const right=rightExtent(),bottom=Math.max(...tables.map(t=>t.position.y+height(t)));
  s.view=[x-60,y-60,right-x+120,Math.max(400,bottom-y+120)];view();
 }
 function endpoint(tid,cid,out){const t=table(tid);return {x:t.position.x+(out?width(t):0),y:t.position.y+layout(t).rows.find(r=>r.column.id===cid).center};}
 function path(a,b){const bend=Math.max(65,Math.abs(b.x-a.x)*.45);return `M${a.x},${a.y} C${a.x+bend},${a.y} ${b.x-bend},${b.y} ${b.x},${b.y}`;}
 function joinPath(a,b){const x=Math.max(a.x,b.x)+100;return `M${a.x},${a.y} C${x},${a.y} ${x},${b.y} ${b.x},${b.y}`;}
 function rightExtent(){return Math.max(...visible().map(t=>t.position.x+width(t)),...doc.links.filter(e=>e.kind==='join'&&table(e.source_table)?.position&&table(e.target_table)?.position).map(e=>Math.max(table(e.source_table).position.x+width(table(e.source_table)),table(e.target_table).position.x+width(table(e.target_table)))+330));}
 function drawEdges(){
  const group=svg.querySelector('.lb-edges');if(!group)return;group.replaceChildren();
  for(const e of doc.links){
   if(!table(e.source_table)?.position||!table(e.target_table)?.position)continue;
   const join=e.kind==='join',a=endpoint(e.source_table,e.source_column,true),b=endpoint(e.target_table,e.target_column,join),d=join?joinPath(a,b):path(a,b);
   node('path',{d,class:'lb-hit','data-edge':e.id},null,group);
   const attrs={d,class:'lb-edge'+(join?' lb-join':'')+(s.selected?.id===e.id?' selected':''),'data-edge':e.id,tabindex:0,role:'button','aria-label':`${table(e.source_table).name}.${table(e.source_table).columns.find(c=>c.id===e.source_column).name} ${join?'join':'to'} ${table(e.target_table).name}.${table(e.target_table).columns.find(c=>c.id===e.target_column).name}: ${join?e.join_type:e.label||'relationship'}`};
   const colors=colorList(traces.edgeColors,e.id),stroke=paint(colors,[a.x,a.y,b.x,b.y],'edge:'+e.id)||(join?'#d89e3a':'var(--lb-accent)'),traced=traces.selected.links.has(e.id),opacity=traces.active&&!traced ? .16 : 1;
   attrs['data-traced']=traced;if(!join)attrs['marker-end']=arrow(colors.length?colors[colors.length-1]:stroke);const line=node('path',attrs,null,group);line.style.stroke=stroke;line.style.opacity=opacity;line.style.strokeWidth=s.selected?.id===e.id?4:traces.active&&traced?3.5:2;
   const text=join?(e.join_type||'Join')+(e.label?' · '+e.label:''):e.label;
   if(text){const label=node('text',{x:join?Math.max(a.x,b.x)+90:(a.x+b.x)/2,y:(a.y+b.y)/2-10,'text-anchor':join?'start':'middle','font-size':12,'data-edge':e.id},short(text,40),group);label.style.opacity=opacity;node('title',{},text,label);}
  }
 }
 function inspector(){
  const e=s.selected?.kind==='edge'?doc.links.find(e=>e.id===s.selected.id):null,t=s.selection.size===1?table([...s.selection][0]):null;
  root.querySelector('.lb-selection').textContent=e?`${table(e.source_table).name} → ${table(e.target_table).name}`:s.selection.size>1?`${s.selection.size} tables selected`:t?t.name:'Select a table or relationship.';
  const input=root.querySelector('.lb-label');input.hidden=!e||!editable;input.value=e?.label||'';
  if(e?.kind==='join'){mode.value='join';setJoinChoice(e.join_type||'Inner join');}updateMode();
  root.querySelector('[data-action=label]').hidden=!e||!editable;
  const remove=root.querySelector('[data-action=remove]');remove.hidden=(!s.selected&&!s.selection.size)||!editable;remove.textContent=s.selection.size?'Remove from canvas':'Delete relationship';
  for(const action of ['color','clear-color']){const button=root.querySelector(`[data-action="${action}"]`);button.hidden=!editable||!s.selection.size;button.disabled=s.saving||(action==='clear-color'&&![...s.selection].some(id=>table(id).color));}
  root.querySelector('.lb-trace-summary').textContent=traces.active?`Downstream trace: ${traces.selected.tables.size-s.selection.size} tables · ${traces.selected.links.size} relationships`:'';
 }
 function draw(){
  traces=lineageTraces(doc,[...s.selection]);paints=new Map();arrows=new Map();svg.replaceChildren();node('defs',{},null,svg);
  node('g',{class:'lb-edges'},null,svg);
  if(!visible().length)node('text',{x:80,y:160,'font-size':20},editable?'Add tables from the catalog to start your lineage.':'No tables placed on this canvas.',svg);
  for(const t of visible()){
   const box=layout(t),w=box.width,h=box.height;
   const traced=traces.selected.tables.has(t.id),flowColors=colorList(traces.nodeColors,t.id),flowPaint=paint(flowColors,[0,0,w,0],'node:'+t.id),custom=t.color||(flowColors.length===1?flowColors[0]:'');
   const g=node('g',{'data-table':t.id,'data-traced':traced,transform:`translate(${t.position.x},${t.position.y})`},null,svg);g.style.opacity=traces.active&&!traced ? .25 : 1;
   const card=node('rect',{width:w,height:h,rx:7,class:'lb-card'+(s.selection.has(t.id)?' selected':'')},null,g);
   const colors=data.node_colors?.[t.role];if(colors){card.style.fill=custom?tint(custom):colors.fill;card.style.stroke=t.color||flowPaint||(traces.active&&traced?'var(--lb-accent)':colors.stroke);card.style.strokeWidth=s.selection.has(t.id)?3.5:traces.active&&traced?2.5:1;g.style.setProperty('--st-text-color',colors.text);g.style.setProperty('--lb-rule',colors.stroke);}
   const color=t.color||flowPaint||colors?.stroke||{source:'#208b79',intermediate:'#bc872e',target:'#477fc4'}[t.role];
   node('rect',{x:0,y:8,width:4,height:46,fill:color},null,g);
   if(flowColors.length>1)node('rect',{x:8,y:3,width:w-16,height:3,fill:flowPaint,rx:1},null,g);
   const header=node('g',{class:'lb-header',tabindex:0,role:'button','aria-pressed':s.selection.has(t.id),'aria-label':`${t.name}, ${t.role}. Arrow keys move this table.`},null,g);
   node('rect',{width:w,height:62,fill:'transparent'},null,header);
   const name=node('text',{x:16,y:25,'font-weight':600,'font-size':15},short(t.name,Math.floor((w-32)/8)),header);node('title',{},t.name+(t.comment?' — '+t.comment:''),name);
   node('text',{x:16,y:47,'font-size':11},short(`${t.role} · ${t.columns.length} columns${t.system?' · '+t.system:''}`,Math.floor((w-32)/6)),header);
   node('line',{x1:0,x2:w,y1:62,y2:62,class:'lb-rule'},null,g);
   for(const x of [w*.38,w*.64])node('line',{x1:x,x2:x,y1:62,y2:h,class:'lb-rule'},null,g);
   for(const row of box.rows){
    const c=row.column,y=row.center;
    for(const [x,value,available]of [[12,c.name,w*.38-24],[w*.38+12,c.data_type,w*.26-24]]){const tx=node('text',{x,y:y+4,'font-size':12},short(value,Math.max(3,Math.floor(available/7))),g);node('title',{},value,tx);}
    const text=node('text',{x:w*.64+10,y:row.expanded?row.top+20:y+4,'font-size':12,'aria-label':c.comment},null,g);
    const lines=row.expanded?row.lines:[short(c.comment,Math.max(3,Math.floor((w*.36-40)/7)))];
    for(const [i,line]of lines.entries())node('tspan',{x:w*.64+10,dy:i?16:0},line,text);node('title',{},c.comment,text);
    if(c.comment){const toggle=node('g',{class:'lb-expand','data-expand':c.id,tabindex:0,role:'button','aria-expanded':row.expanded,'aria-label':`${row.expanded?'Collapse':'Expand'} comment for ${t.name}.${c.name}`},null,g);node('rect',{x:w-28,y:row.top+4,width:24,height:24,rx:3,fill:'transparent'},null,toggle);node('text',{x:w-16,y:row.top+21,'text-anchor':'middle','font-size':14},row.expanded?'−':'+',toggle);}
    node('line',{x1:0,x2:w,y1:row.top+row.height,y2:row.top+row.height,class:'lb-rule'},null,g);
    if(editable)for(const out of [false,true]){const port=node('circle',{cx:out?w:0,cy:y,r:6,class:'lb-port'+(s.pending?.table===t.id&&s.pending?.column===c.id&&out?' pending':''),'data-port':out?'out':'in','data-column':c.id,tabindex:0,role:'button','aria-label':`${out?'Output from':'Input to'} ${t.name}.${c.name}`},null,g);node('title',{},`${out?'Connect from':'Connect to'} ${c.name}`,port);}
   }
   if(!t.columns.length)node('text',{x:16,y:88,'font-size':12},'Add columns in the schema editor.',g);
   if(editable){
    for(const [direction,x,y,rw,rh]of [['n',8,-4,w-16,8],['s',8,h-4,w-16,8],['w',-4,8,8,h-16],['e',w-4,8,8,h-16],['nw',-5,-5,12,12],['ne',w-7,-5,12,12],['sw',-5,h-7,12,12],['se',w-7,h-7,12,12]]){
     const handle=node('rect',{x,y,width:rw,height:rh,class:'lb-resize','data-resize':direction,'aria-label':`Resize ${t.name} ${direction}`},null,g);handle.style.cursor=direction+'-resize';
    }
    // Keep ports above edge handles so connections remain easy to grab.
    g.querySelectorAll('.lb-port').forEach(port=>g.append(port));
   }
  }
  if(s.drag?.kind==='select'){const d=s.drag;node('rect',{x:Math.min(d.x,d.current.x),y:Math.min(d.y,d.current.y),width:Math.abs(d.x-d.current.x),height:Math.abs(d.y-d.current.y),class:'lb-marquee'},null,svg);}
  drawEdges();view();inspector();
 }
 function select(kind,id,additive=false){
  if(kind==='edge'){s.selection.clear();s.selected={kind,id};}
  else{if(!additive)s.selection.clear();s.selection.has(id)?s.selection.delete(id):s.selection.add(id);s.selected=null;}
  draw();svg.focus({preventScroll:true});
 }
 function expand(id){s.expanded.has(id)?s.expanded.delete(id):s.expanded.add(id);draw();svg.focus({preventScroll:true});}
 function connect(tid,cid){
  const p=s.pending;if(!p)return;
  const kind=p.kind||'lineage';
  if(p.table===tid&&p.column===cid){message('Choose a different target column.');return;}
  if(doc.links.some(e=>(e.kind||'lineage')===kind&&((e.source_table===p.table&&e.source_column===p.column&&e.target_table===tid&&e.target_column===cid)||(kind==='join'&&e.target_table===p.table&&e.target_column===p.column&&e.source_table===tid&&e.source_column===cid)))){message('This relationship already exists.');return;}
  if(doc.links.length>=2000){message('The builder supports up to 2,000 relationships.');return;}
  doc.links.push({id:crypto.randomUUID(),source_table:p.table,source_column:p.column,target_table:tid,target_column:cid,label:'',kind,join_type:kind==='join'?joinChoice():''});draw();send();svg.focus({preventScroll:true});
 }
 function add(id,pos){
  if(s.saving||!editable)return;const t=table(id);if(t.position){select('table',id);return;}
  t.canvas_member=true;t.catalog_hidden=false;t.position={x:pos?.x??s.view[0]+80,y:pos?.y??s.view[1]+80};s.selected=null;s.selection=new Set([id]);draw();palette();send();svg.focus({preventScroll:true});
 }
 function palette(){
  const filter=root.querySelector('.lb-search').value.toLowerCase(),list=root.querySelector('.lb-tables');list.replaceChildren();
  function tableButton(t,parent){
   const b=document.createElement('button');b.type='button';b.textContent=t.name;b.dataset.catalogTable=t.id;let dragged=false;
   if(t.color)b.style.borderLeft='4px solid '+t.color;
   const detail=document.createElement('small');detail.textContent=`${t.role} · ${t.columns.length} columns${t.position?' · on canvas':' · drag to canvas'}`;b.append(detail);
   b.onclick=()=>{if(dragged){dragged=false;return;}if(t.position)select('table',t.id);else message('Drag this table onto the canvas, or press Enter to place it.');};b.onkeydown=e=>{if(e.key==='Enter'&&!t.position){e.preventDefault();add(t.id);}};
   b.onpointerdown=e=>{if(e.button!==0||s.saving||!editable)return;e.preventDefault();dragged=false;s.catalogDrag={id:t.id,x:e.clientX,y:e.clientY,moved:false};b.setPointerCapture(e.pointerId);};
   b.onpointermove=e=>{
    const d=s.catalogDrag;if(!d||d.id!==t.id)return;d.moved=d.moved||Math.abs(e.clientX-d.x)+Math.abs(e.clientY-d.y)>5;if(!d.moved)return;
    let ghost=root.querySelector('.lb-catalog-ghost');if(!ghost){ghost=document.createElement('div');ghost.className='lb-catalog-ghost';ghost.textContent=t.name;root.append(ghost);}ghost.style.left=(e.clientX+12)+'px';ghost.style.top=(e.clientY+12)+'px';
    root.querySelectorAll('.lb-drop-hover').forEach(el=>el.classList.remove('lb-drop-hover'));catalogTarget(e)?.classList.add('lb-drop-hover');
   };
   b.onpointerup=e=>{const d=s.catalogDrag;if(!d||d.id!==t.id)return;const target=catalogTarget(e);s.catalogDrag=null;dragged=d.moved;if(b.hasPointerCapture(e.pointerId))b.releasePointerCapture(e.pointerId);clearCatalogDrag();if(!d.moved||s.saving)return;if(target?.matches('[data-folder-drop]'))moveFolder(t,target.dataset.folderDrop||null);else if(target===svg)add(t.id,point(e));};
   b.onpointercancel=()=>{s.catalogDrag=null;clearCatalogDrag();};parent.append(b);
  }
  function dropTarget(el,folder){
   el.dataset.folderDrop=folder||'';
  }
  const members=doc.tables.filter(t=>!t.catalog_hidden&&(t.canvas_member||t.position||t.folder));
  for(const folder of doc.folders){
   const matches=members.filter(t=>t.folder===folder.id&&(t.name.toLowerCase().includes(filter)||folder.name.toLowerCase().includes(filter)));
   if(filter&&!matches.length&&!folder.name.toLowerCase().includes(filter))continue;
   const details=document.createElement('details');details.className='lb-folder';details.dataset.folder=folder.id;details.open=!!filter||s.openFolders.has(folder.id);
   const summary=document.createElement('summary');summary.textContent=folder.name+` (${members.filter(t=>t.folder===folder.id).length})`;details.append(summary);dropTarget(summary,folder.id);
   const body=document.createElement('div');body.className='lb-folder-drop';dropTarget(body,folder.id);for(const t of matches)tableButton(t,body);if(!matches.length){const hint=document.createElement('p');hint.textContent='Drop tables here';body.append(hint);}details.append(body);
   details.ontoggle=()=>{if(!filter){details.open?s.openFolders.add(folder.id):s.openFolders.delete(folder.id);}};list.append(details);
  }
  const unfiled=document.createElement('div');unfiled.className='lb-folder-drop';unfiled.setAttribute('aria-label','Unfiled tables');const label=document.createElement('p');label.textContent='Unfiled · drop here to remove from a folder';unfiled.append(label);dropTarget(unfiled,null);
  for(const t of members.filter(t=>!t.folder&&t.name.toLowerCase().includes(filter)))tableButton(t,unfiled);list.append(unfiled);
 }
 function catalogTarget(e){const target=root.getRootNode().elementFromPoint(e.clientX,e.clientY);return target?.closest('[data-folder-drop]')||target?.closest('.lb-svg');}
 function clearCatalogDrag(){root.querySelector('.lb-catalog-ghost')?.remove();root.querySelectorAll('.lb-drop-hover').forEach(el=>el.classList.remove('lb-drop-hover'));}
 function moveFolder(t,folder){if(s.saving||!editable||(t.folder||null)===folder)return;t.folder=folder;t.canvas_member=true;t.catalog_hidden=false;palette();send();}
 function choosePort(card,port,drag=false){
  s.selected=null;s.selection.clear();
  const tid=card.dataset.table,cid=port.dataset.column,out=port.dataset.port==='out';
  if(mode.value==='join'&&!out){message('Join mode connects two right-side output ports.');return;}
  if(mode.value==='join'&&s.pending&&!(s.pending.table===tid&&s.pending.column===cid)){connect(tid,cid);return;}
  if(out){s.pending={table:tid,column:cid,kind:mode.value};s.drag=drag?{kind:'link'}:null;message(mode.value==='join'?'Select another right-side port to join.':'Choose or drag to a left input port.');draw();svg.focus({preventScroll:true});}
  else connect(tid,cid);
 }
 svg.ondragover=e=>{if(editable&&!s.saving){e.preventDefault();e.dataTransfer.dropEffect='copy';}};svg.ondrop=e=>{e.preventDefault();const id=e.dataTransfer.getData('text/plain');if(table(id))add(id,point(e));};
 svg.onpointerdown=e=>{
  if(e.button!==0||s.saving)return;const port=e.target.closest('[data-port]'),card=e.target.closest('[data-table]'),edge=e.target.closest('[data-edge]'),toggle=e.target.closest('[data-expand]'),resize=e.target.closest('[data-resize]');
  if(e.altKey||s.altPan){e.preventDefault();setAltPan(true);s.drag={kind:'pan',temporaryPan:true,pointerId:e.pointerId,x:e.clientX,y:e.clientY,start:[...s.view]};s.pending=null;root.classList.add('lb-pan-dragging');svg.setPointerCapture(e.pointerId);svg.focus({preventScroll:true});return;}
  if(toggle){e.preventDefault();expand(toggle.dataset.expand);return;}
  if(port&&editable){e.preventDefault();choosePort(card,port,true);return;}
  if(resize&&editable){
   e.preventDefault();const t=table(card.dataset.table),p=point(e),box=layout(t);s.pending=null;s.selected={kind:'table',id:t.id};
   s.selection=new Set([t.id]);
   s.drag={kind:'resize',id:t.id,direction:resize.dataset.resize,x:p.x,y:p.y,start:{...t.position},size:{width:box.width,height:box.height},savedSize:t.size?{...t.size}:null,moved:false};
   svg.setPointerCapture(e.pointerId);svg.focus({preventScroll:true});return;
  }
  if(edge){select('edge',edge.dataset.edge);return;}
  if(card){
   const id=card.dataset.table,additive=e.ctrlKey||e.metaKey;
   if(additive)select('table',id,true);else if(!s.selection.has(id))select('table',id);else{s.selected=null;draw();}
   if(!editable||!s.selection.has(id))return;
   const p=point(e);s.pending=null;s.drag={kind:'move',x:p.x,y:p.y,starts:Object.fromEntries([...s.selection].map(id=>[id,{...table(id).position}])),moved:false};
  }else if(!editable||root.querySelector('.lb-tool').value==='pan'||e.shiftKey){s.drag={kind:'pan',x:e.clientX,y:e.clientY,start:[...s.view]};s.pending=null;}
  else{const p=point(e),initial=e.ctrlKey||e.metaKey?[...s.selection]:[];s.selection=new Set(initial);s.selected=null;s.pending=null;s.drag={kind:'select',x:p.x,y:p.y,current:p,initial};draw();}
  svg.setPointerCapture(e.pointerId);svg.focus({preventScroll:true});
 };
 svg.onpointermove=e=>{
  const d=s.drag;if(!d)return;
  if(d.kind==='pan'){const box=svg.getBoundingClientRect();const scale=Math.max(s.view[2]/box.width,s.view[3]/box.height);s.view=[d.start[0]-(e.clientX-d.x)*scale,d.start[1]-(e.clientY-d.y)*scale,s.view[2],s.view[3]];view();}
  if(d.kind==='move'){const p=point(e);d.moved=d.moved||Math.abs(p.x-d.x)+Math.abs(p.y-d.y)>1;if(!d.moved)return;for(const [id,start]of Object.entries(d.starts))table(id).position={x:start.x+p.x-d.x,y:start.y+p.y-d.y};
   for(const el of svg.querySelectorAll('[data-table]'))if(d.starts[el.dataset.table]){const t=table(el.dataset.table);el.setAttribute('transform',`translate(${t.position.x},${t.position.y})`);}drawEdges();}
  if(d.kind==='select'){
   d.current=point(e);const x=Math.min(d.x,d.current.x),y=Math.min(d.y,d.current.y),right=Math.max(d.x,d.current.x),bottom=Math.max(d.y,d.current.y);
   s.selection=new Set([...d.initial,...visible().filter(t=>t.position.x<=right&&t.position.x+width(t)>=x&&t.position.y<=bottom&&t.position.y+height(t)>=y).map(t=>t.id)]);draw();
  }
  if(d.kind==='resize'){
   const p=point(e),t=table(d.id),dx=p.x-d.x,dy=p.y-d.y,dir=d.direction;
   const w=Math.min(1600,Math.max(320,d.size.width+(dir.includes('e')?dx:dir.includes('w')?-dx:0))),h=Math.min(30000,Math.max(98,d.size.height+(dir.includes('s')?dy:dir.includes('n')?-dy:0)));
   t.size={width:w,height:h};const actual=layout(t);t.position={x:d.start.x+(dir.includes('w')?d.size.width-actual.width:0),y:d.start.y+(dir.includes('n')?d.size.height-actual.height:0)};
   d.moved=true;draw();
  }
  if(d.kind==='link'){let ghost=svg.querySelector('.lb-ghost');if(!ghost)ghost=node('path',{class:'lb-ghost',fill:'none',stroke:'var(--lb-accent)','stroke-dasharray':'5 4','pointer-events':'none'},null,svg);ghost.setAttribute('d',(s.pending.kind==='join'?joinPath:path)(endpoint(s.pending.table,s.pending.column,true),point(e)));}
 };
 svg.onpointerup=e=>{
  root.classList.remove('lb-pan-dragging');
  const d=s.drag;s.drag=null;if(!d)return;
  if(svg.hasPointerCapture(e.pointerId))svg.releasePointerCapture(e.pointerId);
  if(d.kind==='link'){const port=e.target.closest('[data-port]'),tid=port?.closest('[data-table]').dataset.table,cid=port?.dataset.column;
   if(port&&(s.pending.kind==='join'?port.dataset.port==='out':port.dataset.port==='in')&&!(tid===s.pending.table&&cid===s.pending.column))connect(tid,cid);else draw();}
  if((d.kind==='move'||d.kind==='resize')&&d.moved){draw();send();}
  else if(d.kind==='select'||d.kind==='move'){draw();svg.focus({preventScroll:true});}
 };
 function cancelDrag(){const d=s.drag;if(d?.kind==='move')for(const [id,start]of Object.entries(d.starts))table(id).position=start;if(d?.kind==='resize'){table(d.id).position=d.start;table(d.id).size=d.savedSize;}s.drag=null;s.pending=null;root.classList.remove('lb-pan-dragging');draw();}
 svg.onpointercancel=cancelDrag;
 svg.onkeydown=e=>{
  if(e.key==='Escape'){s.selected=null;s.selection.clear();cancelDrag();return;}
  const toggle=e.target.closest('[data-expand]');if(toggle&&(e.key==='Enter'||e.key===' ')){e.preventDefault();expand(toggle.dataset.expand);return;}
  if(s.saving)return;const port=e.target.closest('[data-port]'),card=e.target.closest('[data-table]'),edge=e.target.closest('[data-edge]');
  if((e.key==='Enter'||e.key===' ')&&(port||edge||card)){e.preventDefault();if(port){choosePort(card,port);svg.focus({preventScroll:true});}else select(edge?'edge':'table',edge?.dataset.edge||card.dataset.table,e.ctrlKey||e.metaKey);}
  if(editable&&card&&e.target.closest('.lb-header')&&['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();if(!s.selection.has(card.dataset.table))select('table',card.dataset.table);const step=e.shiftKey?50:10;for(const id of s.selection){const t=table(id);t.position.x+=e.key==='ArrowRight'?step:e.key==='ArrowLeft'?-step:0;t.position.y+=e.key==='ArrowDown'?step:e.key==='ArrowUp'?-step:0;}draw();send();}
 };
 root.onkeydown=e=>{
  const target=e.composedPath()[0];if(target.matches?.('input,textarea,select')||target.isContentEditable||root.querySelector('dialog[open]'))return;
  if(e.key==='Alt'&&!e.ctrlKey&&!e.metaKey&&!e.getModifierState('AltGraph')){e.preventDefault();setAltPan(true);return;}
  const key=e.key.toLowerCase(),modifier=e.ctrlKey||e.metaKey;
  const action=modifier&&key==='z'?(e.shiftKey?'redo':'undo'):modifier&&key==='y'?'redo':e.key==='Delete'?'remove':null;
  if(!action||!editable)return;e.preventDefault();if(s.saving)return;
  if(action==='remove')removeSelected();else history(action);
 };
 svg.onwheel=e=>{e.preventDefault();const p=point(e),factor=e.deltaY>0?1.12:.89;zoom(factor,p);};
 function zoom(factor,p){const w=s.view[2]*factor;if(w<160||w>30000)return;p=p||{x:s.view[0]+s.view[2]/2,y:s.view[1]+s.view[3]/2};s.view=[p.x-(p.x-s.view[0])*factor,p.y-(p.y-s.view[1])*factor,w,s.view[3]*factor];view();}
 function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),3000);}
 function image(format){
  if(!visible().length){message('Place a table on the canvas before exporting an image.');return;}
  const tables=visible(),x=Math.min(...tables.map(t=>t.position.x))-40,y=Math.min(...tables.map(t=>t.position.y))-40;
  const w=rightExtent()-x+40,h=Math.max(...tables.map(t=>t.position.y+height(t)))-y+40;
  const clone=svg.cloneNode(true);clone.setAttribute('xmlns',ns);clone.setAttribute('viewBox',`${x} ${y} ${w} ${h}`);clone.setAttribute('width',w);clone.setAttribute('height',h);
  const originalText=svg.querySelectorAll('text');clone.querySelectorAll('text').forEach((n,i)=>{const style=getComputedStyle(originalText[i]);n.style.fill=style.fill;n.style.fontFamily=style.fontFamily;});
  const originalRules=svg.querySelectorAll('.lb-rule');clone.querySelectorAll('.lb-rule').forEach((n,i)=>n.style.stroke=getComputedStyle(originalRules[i]).stroke);
  const originalShapes=svg.querySelectorAll('.lb-card,.lb-edge');clone.querySelectorAll('.lb-card,.lb-edge').forEach((n,i)=>{const stroke=getComputedStyle(originalShapes[i]).stroke;if(!stroke.includes('url('))n.style.stroke=stroke;});
  const style=getComputedStyle(root),color=style.color,bg=style.getPropertyValue('--lb-bg').trim()||'#fff',accent=style.getPropertyValue('--lb-accent').trim()||'#176db1',border=style.getPropertyValue('--lb-border').trim()||'#a3afbd',card=style.getPropertyValue('--lb-card').trim()||'#f2f5f9';
  clone.querySelectorAll('.lb-port,.lb-hit,.lb-ghost,.lb-resize,.lb-expand,.lb-marquee').forEach(n=>n.remove());
  const css=node('style',{},`.lb-card{fill:${card};stroke:${border}}text{fill:${color};font-family:Arial,sans-serif}.lb-edge{fill:none;stroke:${accent};stroke-width:2}.lb-edge.lb-join{stroke:#d89e3a;stroke-dasharray:6 4}.lb-rule{stroke:${border};opacity:.4}`,null);clone.prepend(css);
  clone.querySelectorAll('[fill="var(--lb-accent)"]').forEach(n=>n.setAttribute('fill',accent));
  clone.prepend(node('rect',{x,y,width:w,height:h,fill:bg}));
  const xml=new XMLSerializer().serializeToString(clone),blob=new Blob([xml],{type:'image/svg+xml;charset=utf-8'});
  if(format==='svg'){download(blob,'lineage-builder.svg');message('SVG exported.');return;}
  if(w*h>16000000||w>8192||h>8192){message('PNG exceeds 16 million pixels or 8,192px per side. Use SVG or bring tables closer together.');return;}
  const url=URL.createObjectURL(blob),img=new Image();img.onload=()=>{try{const c=document.createElement('canvas');c.width=Math.ceil(w);c.height=Math.ceil(h);c.getContext('2d').drawImage(img,0,0);c.toBlob(b=>{if(b){download(b,'lineage-builder.png');message('PNG exported.');}},'image/png');}catch(_){message('PNG export failed. Try SVG.');}finally{URL.revokeObjectURL(url);}};img.onerror=()=>{URL.revokeObjectURL(url);message('PNG export failed. Try SVG.');};img.src=url;
 }
 const dialog=root.querySelector('.lb-create'),form=root.querySelector('.lb-create-form');
 const catalog=data.type_catalog||{'Generic SQL':['INTEGER','VARCHAR','DECIMAL','DATE']};
 const columns=mountColumns(dialog.querySelector('.lb-columns'),[],catalog['Generic SQL']);
 const systems=form.elements.system,previousSystem=systems.value||'Generic SQL';
 systems.replaceChildren();for(const name of Object.keys(catalog)){const option=document.createElement('option');option.value=name;option.textContent=name;option.defaultSelected=name==='Generic SQL';systems.append(option);}
 const other=document.createElement('option');other.value='__custom__';other.textContent='Other / custom';systems.append(other);systems.value=previousSystem;
 function selectedSystem(){return systems.value==='__custom__'?form.elements.custom_system.value.trim():systems.value;}
 function typeOptions(){
  const custom=systems.value==='__custom__';root.querySelector('.lb-custom-system').hidden=!custom;form.elements.custom_system.required=custom;
  const system=Object.keys(catalog).find(name=>name.toLowerCase()===selectedSystem().toLowerCase())||'Generic SQL';
  columns.setOptions(catalog[system]||catalog['Generic SQL']);
 }
 systems.onchange=typeOptions;form.elements.custom_system.oninput=typeOptions;
 root.querySelector('.lb-cancel-create').onclick=()=>dialog.close();
 dialog.oncancel=e=>{if(s.saving)e.preventDefault();};
 form.onsubmit=e=>{
  e.preventDefault();if(!createTable||s.saving)return;
  if(!form.elements.table_name.value.trim()){root.querySelector('.lb-create-error').textContent='Enter a table name.';return;}
  s.creating=true;s.operation={kind:'catalog',before:s.lastSaved};s.saving=true;historyButtons();root.querySelector('.lb-create-error').textContent='Saving table…';
  dialog.querySelectorAll('input,select,button').forEach(el=>el.disabled=true);
  createTable({revision:doc.revision,table:{name:form.elements.table_name.value,role:form.elements.role.value,system:selectedSystem(),comment:form.elements.comment.value,columns:columns.read(),position:null,canvas_member:true}});
 };
 if(s.creating&&(updated||data.error)){
  s.creating=false;dialog.querySelectorAll('input,select,button').forEach(el=>el.disabled=false);
  root.querySelector('.lb-create-error').textContent=data.error||'';
  if(!data.error){dialog.close();form.reset();columns.reset();}
 }
 typeOptions();
 const colorDialog=root.querySelector('.lb-color-dialog'),colorForm=root.querySelector('.lb-color-form'),colorPicker=root.querySelector('.lb-color-picker');
 function assignColor(ids,color){
  if(!editable||s.saving)return;const targets=ids.map(table).filter(t=>t&&(t.color||'')!==color);if(!targets.length)return;
  for(const t of targets)t.color=color;s.selection=new Set(ids.filter(id=>table(id)?.position));s.selected=null;s.pending=null;draw();palette();send();
 }
 function openColor(ids){
  if(!editable||s.saving||!ids.length)return;s.colorTargets=[...ids];colorPicker.value=ids.map(table).find(t=>t?.color)?.color||'#2563eb';
  root.querySelector('.lb-color-targets').textContent=`Apply to ${ids.length} table${ids.length===1?'':'s'}.`;colorDialog.showModal();
 }
 const swatches=root.querySelector('.lb-color-swatches');swatches.replaceChildren();
 for(const [name,color]of [['Blue','#2563eb'],['Green','#16a34a'],['Orange','#f97316'],['Purple','#9333ea'],['Pink','#db2777'],['Cyan','#0891b2']]){
  const button=document.createElement('button');button.type='button';button.setAttribute('aria-label',name);button.title=name+' '+color;button.style.background=color;button.onclick=()=>{colorPicker.value=color;};swatches.append(button);
 }
 colorForm.onsubmit=e=>{e.preventDefault();const ids=s.colorTargets||[];colorDialog.close();assignColor(ids,colorPicker.value);};
 root.querySelector('.lb-color-clear').onclick=()=>{colorDialog.close();assignColor(s.colorTargets||[],'');};root.querySelector('.lb-color-cancel').onclick=()=>colorDialog.close();
 const addDialog=root.querySelector('.lb-add');
 function addChoices(){
  const list=root.querySelector('.lb-add-list'),filter=root.querySelector('.lb-add-search').value.toLowerCase();list.replaceChildren();
  for(const t of doc.tables.filter(t=>(t.catalog_hidden||(!t.canvas_member&&!t.position&&!t.folder))&&t.name.toLowerCase().includes(filter))){
   const button=document.createElement('button');button.type='button';button.textContent=t.name;button.onclick=()=>{const wasHidden=!!t.catalog_hidden;addDialog.close();t.canvas_member=true;t.catalog_hidden=false;palette();send(wasHidden);};list.append(button);
  }
  if(!list.children.length){const text=document.createElement('p');text.textContent='No matching tables to add. Create a table or import schemas first.';list.append(text);}
 }
 root.querySelector('.lb-add-search').oninput=addChoices;root.querySelector('.lb-close-add').onclick=()=>addDialog.close();
 const folderDialog=root.querySelector('.lb-folder-dialog'),folderForm=root.querySelector('.lb-folder-form');
 root.querySelector('.lb-folder-cancel').onclick=()=>folderDialog.close();
 folderForm.onsubmit=e=>{
  e.preventDefault();if(!editable||s.saving)return;const name=folderForm.elements.folder_name.value.trim(),error=root.querySelector('.lb-folder-error');
  if(!name||doc.folders.some(f=>f.name.toLowerCase()===name.toLowerCase())){error.textContent='Enter a unique folder name.';return;}
  if(doc.folders.length>=100){error.textContent='The catalog supports up to 100 folders.';return;}
  const folder={id:crypto.randomUUID(),name};doc.folders.push(folder);s.openFolders.add(folder.id);folderDialog.close();folderForm.reset();palette();send();
 };
 mode.onchange=()=>{s.pending=null;s.selected=null;s.selection.clear();updateMode();draw();};joinSelect.onchange=updateMode;
 const workDialog=root.querySelector('.lb-work-dialog'),workForm=root.querySelector('.lb-work-form'),overwriteWork=root.querySelector('.lb-work-overwrite');
 workForm.elements.work_name.oninput=()=>{overwriteWork.hidden=true;root.querySelector('.lb-work-error').textContent='';};
 function workSaveChoice(){
  overwriteWork.hidden=true;
  const overwrite=!!s.workTarget&&workForm.elements.save_mode.value==='overwrite';
  workForm.elements.work_name.value=overwrite?s.workTarget.name:'';workForm.elements.work_name.readOnly=overwrite;
 }
 workForm.elements.save_mode.onchange=workSaveChoice;
 function openWork(action){
  if(!workAction||s.saving)return;s.workAction=action;s.pending=null;workForm.reset();root.querySelector('.lb-work-error').textContent='';
  s.workTarget=data.current_work||null;root.querySelector('.lb-work-mode').hidden=!s.workTarget;
  workForm.elements.save_mode.value=s.workTarget?'overwrite':'new';workSaveChoice();
  const clearing=action==='clear';root.querySelector('#lb-work-title').textContent=clearing?'Save and clear canvas':'Save canvas';
  root.querySelector('.lb-work-description').textContent=clearing?'Save your design, then clear the canvas and its catalog, folders and relationships. Workspace table schemas stay available through Add table. Load the saved work to restore the diagram.':s.workTarget?'Overwrite the saved design or choose Save as new work to keep a separate copy.':'Save a named copy of the current design in Saved work. Leave the name blank to generate one automatically.';
  root.querySelector('.lb-work-submit').textContent=clearing?'Save and clear':'Save canvas';workDialog.showModal();
 }
 root.querySelector('.lb-work-cancel').onclick=()=>workDialog.close();workDialog.oncancel=e=>{if(s.saving)e.preventDefault();};
 function submitWork(workId){
  if(!workAction||s.saving)return;s.workPending=true;s.saving=true;s.operation={kind:s.workAction==='clear'?'clear':'catalog',before:s.lastSaved};historyButtons();
  overwriteWork.hidden=true;workDialog.querySelectorAll('input,select,button').forEach(el=>el.disabled=true);root.querySelector('.lb-work-error').textContent='Saving…';
  workAction({action:s.workAction,name:workForm.elements.work_name.value.trim(),revision:s.revision,work_id:workId,request_id:crypto.randomUUID()});
 }
 workForm.onsubmit=e=>{
  e.preventDefault();submitWork(workForm.elements.save_mode.value==='overwrite'?s.workTarget?.id:null);
 };
 overwriteWork.onclick=()=>{if(data.work_conflict&&workForm.elements.work_name.value.trim()===data.work_conflict.requested_name)submitWork(data.work_conflict.id);};
 if(s.workPending&&(workDone||data.error)){
  s.workPending=false;workDialog.querySelectorAll('input,select,button').forEach(el=>el.disabled=false);
  if(data.error){root.querySelector('.lb-work-error').textContent=data.error;overwriteWork.hidden=!data.work_conflict||workForm.elements.work_name.value.trim()!==data.work_conflict.requested_name;overwriteWork.textContent=s.workAction==='clear'?'Overwrite and clear':'Overwrite saved work';}
  else{workDialog.close();if(s.workAction==='clear'){s.selection.clear();s.selected=null;s.pending=null;s.openFolders.clear();s.expanded.clear();s.view=[0,0,1200,700];root.querySelector('.lb-search').value='';}}
 }
 root.querySelector('[data-action=create]').hidden=!createTable;
 root.querySelector('.lb-search').oninput=palette;
 root.querySelectorAll('[data-action]').forEach(button=>{button.onclick=()=>{
  const action=button.dataset.action;
  if(action==='fit')fit();if(action==='in')zoom(.8);if(action==='out')zoom(1.25);
  if(action==='full'){if(document.fullscreenElement)document.exitFullscreen();else root.requestFullscreen?.().catch(()=>message('Full screen is unavailable.'));}
  if(action==='export'){openExport();return;}
  if(!editable||s.saving)return;
  if(action==='save-work')openWork('save');if(action==='clear-canvas')openWork('clear');
  if(action==='undo'||action==='redo')history(action);
  if(action==='color')openColor([...s.selection]);if(action==='clear-color')assignColor([...s.selection],'');
  if(action==='add'){s.pending=null;addChoices();addDialog.showModal();}
  if(action==='folder'){root.querySelector('.lb-folder-error').textContent='';folderDialog.showModal();}
  if(action==='create'&&createTable){s.pending=null;root.querySelector('.lb-create-error').textContent='';dialog.showModal();}
  if(action==='label'&&s.selected?.kind==='edge'){const link=doc.links.find(e=>e.id===s.selected.id);link.label=root.querySelector('.lb-label').value;if(link.kind==='join')link.join_type=joinChoice();draw();send();}
  if(action==='remove')removeSelected();
 };});
 function closeMenu(restoreFocus=false){
  exportButton.setAttribute('aria-expanded','false');
  if(contextMenu.hidden)return;contextMenu.hidden=true;
  if(restoreFocus)(s.menuReturn?.isConnected?s.menuReturn:svg).focus({preventScroll:true});
 }
 function selectAll(){s.pending=null;s.selected=null;s.selection=new Set(visible().map(t=>t.id));draw();svg.focus({preventScroll:true});}
 function menuItem(label,action,disabled=false){
  const button=document.createElement('button');button.type='button';button.role='menuitem';button.tabIndex=-1;button.textContent=label;button.disabled=disabled;
  button.onclick=()=>{closeMenu(true);action();};contextMenu.append(button);
 }
 function showMenu(x,y){
  contextMenu.hidden=false;contextMenu.style.left='0px';contextMenu.style.top='0px';
  contextMenu.style.left=Math.max(4,Math.min(x,window.innerWidth-contextMenu.offsetWidth-4))+'px';contextMenu.style.top=Math.max(4,Math.min(y,window.innerHeight-contextMenu.offsetHeight-4))+'px';
  (contextMenu.querySelector('button:not(:disabled)')||contextMenu).focus({preventScroll:true});
 }
 function openExport(){
  if(!contextMenu.hidden&&contextMenu.getAttribute('aria-label')==='Export options'){closeMenu(true);return;}
  closeMenu(false);setAltPan(false);contextMenu.replaceChildren();contextMenu.setAttribute('aria-label','Export options');s.menuReturn=exportButton;
  for(const format of ['svg','png'])menuItem(format.toUpperCase(),()=>image(format),!visible().length);
  menuItem('Editable canvas (JSON)',exportCanvas,s.saving);
  exportButton.setAttribute('aria-expanded','true');const anchor=exportButton.getBoundingClientRect();showMenu(anchor.left,anchor.bottom+4);
 }
 exportButton.onkeydown=e=>{if(e.key==='ArrowDown'){e.preventDefault();e.stopPropagation();openExport();}};
 function exportCanvas(){download(new Blob([JSON.stringify(doc,null,2)],{type:'application/json'}),'lineage-work.json');message('Editable canvas exported. Import it in Saved work to continue editing.');}
 function openMenu(e){
  const target=e.composedPath()[0];if(target.closest('input,textarea,select,[contenteditable],dialog,.lb-context'))return;
  const catalog=target.closest('[data-catalog-table]'),folder=target.closest('.lb-folder'),card=target.closest('[data-table]'),edge=target.closest('[data-edge]');
  if(!target.closest('.lb-board,.lb-palette'))return;
  if(!editable)return;e.preventDefault();closeMenu(false);setAltPan(false);contextMenu.replaceChildren();
  s.menuReturn=catalog?root.querySelector('.lb-search'):svg;
  const busy=s.saving,toolbar=action=>root.querySelector(`[data-action="${action}"]`).click();
  const separate=()=>contextMenu.append(document.createElement('hr'));
  const undoRedo=()=>{menuItem('Undo',()=>history('undo'),busy||!s.undo.length);menuItem('Redo',()=>history('redo'),busy||!s.redo.length);};
  const removeTable=t=>{select('table',t.id);removeSelected();};
  const comments=t=>{
   const columns=t.columns.filter(c=>c.comment);if(!columns.length)return;
   menuItem('Expand comments',()=>{for(const c of columns)s.expanded.add(c.id);draw();});
   menuItem('Collapse comments',()=>{for(const c of columns)s.expanded.delete(c.id);draw();});
  };
  if(catalog){
   const t=table(catalog.dataset.catalogTable);contextMenu.setAttribute('aria-label','Catalog table options');
   menuItem('Select table on canvas',()=>select('table',t.id),busy||!t.position);
   menuItem('Add to canvas',()=>add(t.id),busy||!!t.position);
   menuItem('Remove from canvas',()=>removeTable(t),busy||!t.position);
   menuItem('Set trace color',()=>openColor([t.id]),busy);menuItem('Clear assigned color',()=>assignColor([t.id],''),busy||!t.color);
   separate();
   menuItem('Move to Unfiled',()=>moveFolder(t,null),busy||!t.folder);
   for(const f of doc.folders)menuItem('Move to folder: '+f.name,()=>moveFolder(t,f.id),busy||t.folder===f.id);
   separate();menuItem('Remove from catalog',()=>{t.catalog_hidden=true;palette();send();},busy);undoRedo();
  }else if(card){
   const t=table(card.dataset.table),wasSelected=s.selection.has(t.id),previousSelection=new Set(s.selection);if(!busy&&!wasSelected)select('table',t.id);
   contextMenu.setAttribute('aria-label','Table options');
   menuItem('Select table',()=>select('table',t.id),busy);
   menuItem(wasSelected?'Deselect table':'Add to selection',()=>{if(!wasSelected)s.selection=previousSelection;select('table',t.id,true);},busy);
   menuItem('Select all tables',selectAll,busy||!visible().length);
   menuItem(s.selection.size>1?'Delete selected from canvas':'Remove from canvas',removeSelected,busy);
   menuItem('Set trace color',()=>openColor([...s.selection]),busy);menuItem('Clear assigned color',()=>assignColor([...s.selection],''),busy||![...s.selection].some(id=>table(id).color));
   if(t.catalog_hidden)menuItem('Add to catalog',()=>{t.catalog_hidden=false;t.canvas_member=true;palette();send();},busy);
   comments(t);separate();undoRedo();
  }else if(edge){
   if(!busy)select('edge',edge.dataset.edge);contextMenu.setAttribute('aria-label','Relationship options');
   menuItem('Select relationship',()=>select('edge',edge.dataset.edge),busy);
   menuItem('Edit relationship label',()=>root.querySelector('.lb-label').focus(),busy);
   menuItem('Delete relationship',removeSelected,busy);separate();undoRedo();
  }else if(target.closest('.lb-palette')){
   contextMenu.setAttribute('aria-label','Catalog options');
   if(folder)menuItem(folder.open?'Collapse folder':'Expand folder',()=>{folder.open=!folder.open;});
   if(folder){const ids=doc.tables.filter(t=>t.folder===folder.dataset.folder).map(t=>t.id);menuItem('Set folder trace color',()=>openColor(ids),busy||!ids.length);menuItem('Clear folder colors',()=>assignColor(ids,''),busy||!ids.some(id=>table(id).color));}
   menuItem('Create table',()=>toolbar('create'),busy||!createTable);menuItem('Add table',()=>toolbar('add'),busy);
   menuItem('New folder',()=>toolbar('folder'),busy);separate();undoRedo();
  }else{
   contextMenu.setAttribute('aria-label','Canvas options');
   menuItem('Select all tables',selectAll,busy||!visible().length);
   menuItem('Clear selection',()=>{s.selection.clear();s.selected=null;s.pending=null;draw();},busy||(!s.selection.size&&!s.selected));
   menuItem('Delete selected',removeSelected,busy||(!s.selection.size&&!s.selected));separate();undoRedo();separate();
   menuItem('Use Select tables tool',()=>{tool.value='select';},busy);menuItem('Use Pan tool',()=>{tool.value='pan';},busy);
   menuItem('Create table',()=>toolbar('create'),busy||!createTable);menuItem('Add table',()=>toolbar('add'),busy);
   menuItem('Fit diagram',()=>fit(),!visible().length);menuItem('Zoom in',()=>zoom(.8));menuItem('Zoom out',()=>zoom(1.25));
   menuItem('Full screen',()=>toolbar('full'));menuItem('Export SVG',()=>image('svg'),!visible().length);menuItem('Export PNG',()=>image('png'),!visible().length);
   menuItem('Export editable canvas (JSON)',exportCanvas,busy);menuItem('Save canvas',()=>openWork('save'),busy||!workAction);menuItem('Clear canvas',()=>openWork('clear'),busy||!workAction);
  }
  const anchor=target.getBoundingClientRect(),x=e.clientX||anchor.left+8,y=e.clientY||anchor.top+8;
  showMenu(x,y);
 }
 root.oncontextmenu=openMenu;
 contextMenu.onkeydown=e=>{
  const items=[...contextMenu.querySelectorAll('button:not(:disabled)')],index=items.indexOf(e.target);
  if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();e.stopPropagation();const next=e.key==='Home'?0:e.key==='End'?items.length-1:(index+(e.key==='ArrowDown'?1:-1)+items.length)%items.length;items[next]?.focus();}
  if(e.key==='Escape'){e.preventDefault();e.stopPropagation();closeMenu(true);}if(e.key==='Tab')closeMenu(false);
 };
 closeMenu(false);
 root.querySelector('.lb-palette').hidden=!editable;
 for(const selector of ['[data-action=add]','[data-action=undo]','[data-action=redo]','.lb-connection-options','.lb-tool-options'])root.querySelector(selector).hidden=!editable;
 for(const action of ['save-work','clear-canvas'])root.querySelector(`[data-action="${action}"]`).hidden=!workAction;
 root.querySelector('.lb-layout').style.gridTemplateColumns=editable?'':'1fr';
 root.querySelector('.lb-hint').textContent=editable?'Select tables to highlight their full downstream trace. Set a trace color for selected tables or a catalog folder. Ctrl-click/drag empty space selects a group; drag boxes to move. Hold Alt to pan. Catalog tables drag onto canvas/folders. Resize edges/corners; + expands comments. Ctrl+Z / Ctrl+Y undo/redo; Delete removes selected boxes or lines. Edits save automatically.':'Select a table to highlight its downstream trace. Expand comments with +. Hold Alt or drag empty space to pan, scroll to zoom, or use Fit diagram.';
 draw();palette();historyButtons();message(data.error|| (s.saving?'Saving…':editable?(s.pending?'Saved · choose another column, or Escape to finish':'All changes saved'):'Authored lineage'));
 if(showWorkResult&&!data.error)message(data.work_result.message);
 if(!s.initialFit){fit();s.initialFit=true;}
 return ()=>{panEvents.abort();closeMenu(false);};
}
"""

_CANVAS = st.components.v2.component("dataforge_lineage_builder", html=BODY, css=CSS,
    js=JS + "\nexport default function(c){return mountBuilder(c.parentElement,c.data,v=>c.setTriggerValue('edit',v),v=>c.setTriggerValue('create_table',v),v=>c.setTriggerValue('work_action',v));}\n")

_COLUMN_EDITOR = st.components.v2.component("dataforge_schema_columns", html='<div class="lb-root">'+COLUMN_BODY+'</div>',
    css=CSS, js=COLUMN_JS + "\nexport default function(c){mountColumns(c.parentElement.querySelector('.lb-columns'),c.data.rows,c.data.options,v=>c.setStateValue('rows',v));}\n")


def column_editor(rows: list[dict], system: str, key: str) -> list[dict]:
    """Use the canvas's type-or-choose column fields inside the native table form."""
    result = _COLUMN_EDITOR(data={"rows": rows, "options": TYPE_CATALOG.get(system, TYPE_CATALOG["Generic SQL"])},
                            default={"rows": rows}, key=key, on_rows_change=lambda: None, height="content")
    return result.rows


def canvas(document: BuilderDocument, key: str, on_edit, error: str = "", on_create=None, node_colors: dict | None = None,
           on_work=None, work_result: dict | None = None, current_work: dict | None = None, work_conflict: dict | None = None):
    return _CANVAS(data={"document": document.model_dump(), "error": error, "type_catalog": TYPE_CATALOG,
                         "node_colors": node_colors or builder_node_colors(None), "work_result": work_result,
                         "current_work": current_work, "work_conflict": work_conflict}, key=key,
                   on_edit_change=on_edit, on_create_table_change=on_create or (lambda: None),
                   on_work_action_change=on_work or (lambda: None), height="content")


def builder_html(document: BuilderDocument, *, node_colors: dict | None = None) -> bytes:
    """Export a fully offline interactive presentation with inert imported text."""
    payload = json.dumps({"document": document.model_dump(), "node_colors": node_colors or builder_node_colors(None, dark=False)}).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>GraveTrail · Authored lineage</title><style>body{margin:24px;font-family:Arial,sans-serif}"
            + CSS + "</style></head><body><h1>Authored lineage</h1>" + BODY + "<script>" + JS
            + "\nmountBuilder(document," + payload + ",null);</script></body></html>").encode()
