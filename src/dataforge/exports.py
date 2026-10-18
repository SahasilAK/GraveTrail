"""Portable reports and an offline, dependency-free interactive SVG graph."""
from __future__ import annotations

import csv
import html
import io
import json
import zipfile

import networkx as nx

from dataforge.asset_identity import asset_job
from dataforge.configuration import VisualizationSettings
from dataforge.ingestion import safe_relative


def path_rows(report):
    """One ordered CSV row per path/step/evidence, retaining incomplete-path markers."""
    rows = []
    for path in report["paths"]:
        common = {"path_id": path["path_id"], "path": " -> ".join(path["nodes"]),
                  "direction": report["direction"], "boundary": path["boundary"],
                  "report_truncated": report["truncated"]}
        if not path["steps"]:
            rows.append({**common, "step": 0, "source": path["nodes"][0], "target": ""})
        for i, step in enumerate(path["steps"], 1):
            for evidence in step["evidence"] or [{}]:
                rows.append({**common, "step": i, "source": step["source"], "target": step["target"],
                             "intermediates": ", ".join(step["intermediates"]), **evidence})
    return rows


GRAPH_CSS = """
.df-graph{font:14px/1.5 system-ui,sans-serif;color:var(--st-text-color,#23334a);background:var(--st-background-color,#fff);padding:12px;box-sizing:border-box;
--node-neutral:#edf0f4;--node-unresolved:#fff0d4;--node-temporary:#ece7f7;--node-source:#e0efeb;--node-table:#e3ecfb;--node-text:#23334a;--node-border:#8d9cb1}
.df-graph .toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding:0 0 12px}
.df-graph button,.df-graph input{font:inherit;min-height:36px;padding:6px 12px;border:1px solid var(--st-border-color,#bdc8d6);border-radius:7px;background:transparent;color:inherit;box-sizing:border-box;max-width:100%}
.df-graph button{cursor:pointer;touch-action:manipulation}.df-graph button:active{transform:scale(.97)}
.df-graph :is(button,input):focus-visible{outline:2px solid var(--st-primary-color,#2869c7);outline-offset:3px}
.df-graph svg{display:block;width:100%;height:420px;border:1px solid var(--st-border-color,#bdc8d6);border-radius:10px;touch-action:none;background:var(--st-secondary-background-color,#f5f7fa)}
.df-graph .node{cursor:pointer}.df-graph .node:focus rect,.df-graph .edge:focus{stroke:#c47b18;stroke-width:4;outline:none}
.df-graph .edge{cursor:pointer;stroke:#829ab1;stroke-width:2;fill:none}
.df-graph .chosen{stroke:#d67d0d!important;stroke-width:4!important}
.df-graph .edge.chosen{stroke-width:var(--df-selected-edge-width,4)!important}
.df-graph .detail{white-space:pre-wrap;overflow-wrap:anywhere;max-height:260px;overflow:auto;font:13px/1.7 ui-monospace,Consolas,monospace;padding:12px;border-radius:8px;background:var(--st-secondary-background-color,#f5f7fa)}
.df-graph .hint{font-size:12px;color:inherit;opacity:.8}
@media(prefers-color-scheme:dark){.df-graph{--node-neutral:#303b48;--node-unresolved:#4c3823;--node-temporary:#3b3354;--node-source:#203f3d;--node-table:#273d58;--node-text:#edf2f9;--node-border:#7489a3}}
@media(prefers-reduced-motion:reduce){.df-graph button:active{transform:none}}
@media(prefers-contrast:more){.df-graph .hint{opacity:1}.df-graph button,.df-graph input{border-color:currentColor}}
"""


GRAPH_JS = r"""
function mountGraph(root, data, notify) {
 const svg=root.querySelector('svg'), stage=root.querySelector('.stage'), details=root.querySelector('.detail');
 const appearance=data.appearance||{},labels=appearance.graph_labels||'compact';
 const edgeWidth=appearance.graph_edge_width||2;
 root.querySelector('.df-graph').style.setProperty('--df-selected-edge-width',edgeWidth+2);
 const ns='http://www.w3.org/2000/svg';
 const make=(tag,attrs,parent)=>{const e=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,v));parent.appendChild(e);return e};
 stage.replaceChildren();
 const nodes=new Map(data.nodes.map(n=>[n.asset_id,n]));
 const nodeLabel=n=>n.job_id&&n.job_id!=='workspace'?n.name+' [job: '+n.job_id+']':n.name;
 let width=Math.max(700,...data.nodes.map(n=>n.x+n.width+35)),height=Math.max(360,...data.nodes.map(n=>n.y+90));
 let box=[0,0,width,height];
 const view=()=>svg.setAttribute('viewBox',box.join(' '));view();
 const highlight=(ids)=>{stage.querySelectorAll('.chosen').forEach(e=>e.classList.remove('chosen'));ids.forEach(id=>{stage.querySelectorAll('[data-node]').forEach(e=>{if(e.dataset.node===id)e.classList.add('chosen')})});};
 const inspectNode=(n)=>{
   let related=new Set([n.asset_id]),pending=[n.asset_id];
   while(pending.length){let id=pending.pop();data.edges.forEach(e=>{if(e.target===id&&!related.has(e.source)){related.add(e.source);pending.push(e.source)}})}
   highlight(related);stage.querySelectorAll('[data-edge]').forEach(p=>{let e=data.edges[Number(p.dataset.edge)];if(related.has(e.source)&&related.has(e.target))p.classList.add('chosen')});
   details.textContent=nodeLabel(n)+'\n'+(n.temporary?'Temporary asset':'Persistent or external asset')+'\n'+data.edges.filter(e=>e.source===n.asset_id||e.target===n.asset_id).map(e=>nodeLabel(nodes.get(e.source))+' → '+nodeLabel(nodes.get(e.target))+'\n'+e.evidence.map(v=>(v.relative_path||'')+':'+v.start_line+'–'+v.end_line+' '+(v.kind||'')+' ['+(v.status||'')+']').join('\n')).join('\n\n');
   if(notify)notify({node:n.asset_id});
 };
 data.edges.forEach((edge,i)=>{
   const a=nodes.get(edge.source),b=nodes.get(edge.target);
   let x1=a.x+a.width,y1=a.y+24,x2=b.x,y2=b.y+24;
   const d=edge.source===edge.target?`M ${x1} ${y1} c 70 -80 ${-a.width-25} -80 ${5-a.width} 0`:`M ${x1} ${y1} C ${x1+70} ${y1} ${x2-70} ${y2} ${x2} ${y2}`;
   const p=make('path',{d,'class':'edge','marker-end':'url(#df-arrow)','data-edge':i,tabindex:0,role:'button','aria-label':nodeLabel(a)+' to '+nodeLabel(b)},stage);
   p.style.strokeWidth=edgeWidth;
   const show=()=>{highlight(new Set([edge.source,edge.target]));p.classList.add('chosen');details.textContent=nodeLabel(a)+' → '+nodeLabel(b)+'\n'+(edge.intermediates.length?'Via '+edge.intermediates.join(', ')+'\n':'')+edge.evidence.map(v=>(v.relative_path||'')+':'+v.start_line+'–'+v.end_line+' '+v.kind+'\n'+v.code).join('\n\n');if(notify)notify({edge:i})};
   p.onclick=show;p.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();show()}};
 });
 data.nodes.forEach(n=>{
   const g=make('g',{'class':'node',transform:`translate(${n.x},${n.y})`,tabindex:0,role:'button','aria-label':nodeLabel(n)},stage);
   const color=appearance.graph_palette==='neutral'?'var(--node-neutral)':n.kind==='unresolved'?'var(--node-unresolved)':n.temporary?'var(--node-temporary)':n.source?'var(--node-source)':'var(--node-table)';
   make('rect',{width:n.width,height:48,rx:9,fill:color,stroke:'var(--node-border)','data-node':n.asset_id},g);
   if(labels!=='hidden'){
     const text=make('text',{x:12,y:29,fill:'var(--node-text)','font-size':13},g);
     const label=nodeLabel(n);text.textContent=labels==='compact'&&label.length>27?label.slice(0,26)+'…':label;
     if(labels==='full'&&text.getComputedTextLength()>n.width-24){text.setAttribute('textLength',n.width-24);text.setAttribute('lengthAdjust','spacingAndGlyphs')}
   }
   make('title',{},g).textContent=nodeLabel(n);
   g.onclick=()=>inspectNode(n);g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();inspectNode(n)}};
 });
 root.querySelector('.fit').onclick=()=>{box=[0,0,width,height];view()};
 const zoom=(f)=>{box=[box[0]+box[2]*(1-f)/2,box[1]+box[3]*(1-f)/2,box[2]*f,box[3]*f];view()};
 root.querySelector('.plus').onclick=()=>zoom(.8);root.querySelector('.minus').onclick=()=>zoom(1.25);
 svg.onwheel=e=>{e.preventDefault();zoom(e.deltaY>0?1.1:.9)};
 let drag=null;
 svg.onpointerdown=e=>{if(e.target===svg){drag=[e.clientX,e.clientY,...box];svg.setPointerCapture(e.pointerId)}};
 svg.onpointermove=e=>{if(drag){box=[drag[2]-(e.clientX-drag[0])*drag[4]/svg.clientWidth,drag[3]-(e.clientY-drag[1])*drag[5]/svg.clientHeight,drag[4],drag[5]];view()}};
 svg.onpointerup=()=>drag=null;svg.onpointercancel=()=>drag=null;
 root.querySelector('.find').oninput=e=>{let value=e.target.value.toLowerCase();highlight(new Set(data.nodes.filter(n=>value&&nodeLabel(n).toLowerCase().includes(value)).map(n=>n.asset_id)))};
}
"""

GRAPH_BODY = """<div class="df-graph"><div class="toolbar"><button class="fit">Fit graph</button><button class="plus" aria-label="Zoom in">+</button><button class="minus" aria-label="Zoom out">−</button><input class="find" aria-label="Find a node" placeholder="Find a node"><span class="hint">Select a node or edge for evidence. Drag background to pan.</span></div><svg role="group" aria-label="Directed lineage graph"><defs><marker id="df-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#829ab1"/></marker></defs><g class="stage"></g></svg><pre class="detail" aria-live="polite">Select a relationship to inspect its evidence.</pre></div>"""


def graph_data(graph, appearance: VisualizationSettings | None = None) -> dict:
    appearance = appearance or VisualizationSettings()
    condensed = nx.condensation(graph.graph)
    groups = list(nx.topological_generations(condensed))
    width = min(700, max([215] + [len(n["name"]) * 7 + 24 for n in graph.nodes.values()])) if appearance.graph_labels == "full" else 215
    nodes = []
    for level, components in enumerate(groups):
        ids = sorted(n for c in components for n in condensed.nodes[c]["members"])
        for row, node in enumerate(ids):
            attrs = dict(graph.nodes[node])
            attrs.update(x=20 + level * (width + 85), y=20 + row * 85, width=width,
                         source=graph.graph.in_degree(node) == 0, job_id=asset_job(attrs))
            nodes.append(attrs)
    edges = [{"source": s, "target": t, "evidence": a["evidence"], "intermediates": a.get("intermediates", [])}
             for s, t, a in graph.graph.edges(data=True)]
    return {"nodes": nodes, "edges": edges, "appearance": appearance.model_dump(include={
        "graph_labels", "graph_palette", "graph_edge_width"})}


def graph_html(graph, appearance: VisualizationSettings | None = None) -> str:
    data = json.dumps(graph_data(graph, appearance), default=str).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>GraveTrail lineage</title><style>body{margin:20px}' + GRAPH_CSS + '</style></head><body>'
            '<h1>GraveTrail lineage</h1><p>Static dependencies with source evidence. Logical ordering is not execution order.</p>'
            + GRAPH_BODY + '<script>' + GRAPH_JS + '\nmountGraph(document.body,' + data + ',null);</script></body></html>')


def report_csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    for row in rows:
        writer.writerow({k: "'" + str(v) if str(v).startswith(("=", "+", "-", "@", "\t", "\r")) else v for k, v in row.items()})
    return stream.getvalue()


def report_html(rows: list[dict]) -> str:
    header = "".join(f"<th>{html.escape(k)}</th>" for k in (rows[0] if rows else []))
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in r.values()) + "</tr>" for r in rows)
    return '<!doctype html><html lang="en"><meta charset="utf-8"><title>GraveTrail report</title><style>body{font:14px system-ui;margin:24px}table{border-collapse:collapse}td,th{padding:8px;border:1px solid #ccd;text-align:left;white-space:pre-wrap}</style><h1>GraveTrail report</h1><table><thead><tr>' + header + '</tr></thead><tbody>' + body + '</tbody></table></html>'


def source_bundle(store, file_ids: list[str], versions: dict | None = None) -> bytes:
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
