"""Portable reports and an offline, dependency-free interactive SVG graph."""
from __future__ import annotations

import csv
import html
import io
import json
import zipfile

import networkx as nx

from dataforge.ingestion import safe_relative

GRAPH_CSS = """
.df-graph{font:14px system-ui,sans-serif;color:var(--st-text-color,#17324d);background:var(--st-background-color,#fff)}
.df-graph .toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding:10px 0}
.df-graph button,.df-graph input{font:inherit;padding:7px 12px;border:1px solid #99afc5;border-radius:5px;background:transparent;color:inherit}
.df-graph button{cursor:pointer}.df-graph svg{width:100%;height:420px;border:1px solid #91a5b94d;border-radius:8px;touch-action:none;background:var(--st-secondary-background-color,#f5f8fc)}
.df-graph .node{cursor:pointer}.df-graph .node:focus rect{stroke:#cc7a00;stroke-width:4}
.df-graph .edge{cursor:pointer;stroke:#829ab1;stroke-width:2;fill:none}
.df-graph .chosen{stroke:#d67d0d!important;stroke-width:4!important}
.df-graph .detail{white-space:pre-wrap;overflow-wrap:anywhere;max-height:260px;overflow:auto;font-size:13px;line-height:1.6}
.df-graph .hint{font-size:12px;color:inherit;opacity:.8}
"""

GRAPH_JS = r"""
function mountGraph(root, data, notify) {
 const svg=root.querySelector('svg'), stage=root.querySelector('.stage'), details=root.querySelector('.detail');
 const ns='http://www.w3.org/2000/svg';
 const make=(tag,attrs,parent)=>{const e=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,v));parent.appendChild(e);return e};
 stage.replaceChildren();
 const nodes=new Map(data.nodes.map(n=>[n.asset_id,n]));
 let width=Math.max(700,...data.nodes.map(n=>n.x+250)),height=Math.max(360,...data.nodes.map(n=>n.y+90));
 let box=[0,0,width,height];
 const view=()=>svg.setAttribute('viewBox',box.join(' '));view();
 const highlight=(ids)=>{stage.querySelectorAll('.chosen').forEach(e=>e.classList.remove('chosen'));ids.forEach(id=>{stage.querySelectorAll('[data-node]').forEach(e=>{if(e.dataset.node===id)e.classList.add('chosen')})});};
 const inspectNode=(n)=>{
   let related=new Set([n.asset_id]),pending=[n.asset_id];
   while(pending.length){let id=pending.pop();data.edges.forEach(e=>{if(e.target===id&&!related.has(e.source)){related.add(e.source);pending.push(e.source)}})}
   highlight(related);stage.querySelectorAll('[data-edge]').forEach(p=>{let e=data.edges[Number(p.dataset.edge)];if(related.has(e.source)&&related.has(e.target))p.classList.add('chosen')});
   details.textContent=n.name+'\n'+(n.temporary?'Temporary asset':'Persistent or external asset')+'\n'+data.edges.filter(e=>e.source===n.asset_id||e.target===n.asset_id).map(e=>nodes.get(e.source).name+' → '+nodes.get(e.target).name+'\n'+e.evidence.map(v=>(v.relative_path||'')+':'+v.start_line+'–'+v.end_line+' '+(v.kind||'')+' ['+(v.status||'')+']').join('\n')).join('\n\n');
   if(notify)notify({node:n.asset_id});
 };
 data.edges.forEach((edge,i)=>{
   const a=nodes.get(edge.source),b=nodes.get(edge.target);
   let x1=a.x+215,y1=a.y+24,x2=b.x,y2=b.y+24;
   const d=edge.source===edge.target?`M ${x1} ${y1} c 70 -80 -240 -80 -210 0`:`M ${x1} ${y1} C ${x1+70} ${y1} ${x2-70} ${y2} ${x2} ${y2}`;
   const p=make('path',{d,'class':'edge','marker-end':'url(#df-arrow)','data-edge':i,tabindex:0,role:'button','aria-label':a.name+' to '+b.name},stage);
   const show=()=>{highlight(new Set([edge.source,edge.target]));p.classList.add('chosen');details.textContent=a.name+' → '+b.name+'\n'+(edge.intermediates.length?'Via '+edge.intermediates.join(', ')+'\n':'')+edge.evidence.map(v=>(v.relative_path||'')+':'+v.start_line+'–'+v.end_line+' '+v.kind+'\n'+v.code).join('\n\n');if(notify)notify({edge:i})};
   p.onclick=show;p.onkeydown=e=>{if(e.key==='Enter')show()};
 });
 data.nodes.forEach(n=>{
   const g=make('g',{'class':'node',transform:`translate(${n.x},${n.y})`,tabindex:0,role:'button','aria-label':n.name},stage);
   const color=n.kind==='unresolved'?'#fff1d6':n.temporary?'#e5e1f8':n.source?'#d6eeed':'#dfebfc';
   make('rect',{width:215,height:48,rx:6,fill:color,stroke:'#6c8bab','data-node':n.asset_id},g);
   const text=make('text',{x:12,y:29,fill:'#17324d','font-size':13},g);text.textContent=n.name.length>27?n.name.slice(0,26)+'…':n.name;
   make('title',{},g).textContent=n.name;
   g.onclick=()=>inspectNode(n);g.onkeydown=e=>{if(e.key==='Enter')inspectNode(n)};
 });
 root.querySelector('.fit').onclick=()=>{box=[0,0,width,height];view()};
 const zoom=(f)=>{box=[box[0]+box[2]*(1-f)/2,box[1]+box[3]*(1-f)/2,box[2]*f,box[3]*f];view()};
 root.querySelector('.plus').onclick=()=>zoom(.8);root.querySelector('.minus').onclick=()=>zoom(1.25);
 svg.onwheel=e=>{e.preventDefault();zoom(e.deltaY>0?1.1:.9)};
 let drag=null;
 svg.onpointerdown=e=>{if(e.target===svg){drag=[e.clientX,e.clientY,...box];svg.setPointerCapture(e.pointerId)}};
 svg.onpointermove=e=>{if(drag){box=[drag[2]-(e.clientX-drag[0])*drag[4]/svg.clientWidth,drag[3]-(e.clientY-drag[1])*drag[5]/svg.clientHeight,drag[4],drag[5]];view()}};
 svg.onpointerup=()=>drag=null;
 root.querySelector('.find').oninput=e=>{let value=e.target.value.toLowerCase();highlight(new Set(data.nodes.filter(n=>value&&n.name.toLowerCase().includes(value)).map(n=>n.asset_id)))};
}
"""

GRAPH_BODY = """<div class="df-graph"><div class="toolbar"><button class="fit">Fit graph</button><button class="plus" aria-label="Zoom in">+</button><button class="minus" aria-label="Zoom out">−</button><input class="find" aria-label="Find a node" placeholder="Find a node"><span class="hint">Select a node or edge for evidence. Drag background to pan.</span></div><svg role="group" aria-label="Directed lineage graph"><defs><marker id="df-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#829ab1"/></marker></defs><g class="stage"></g></svg><pre class="detail" aria-live="polite">Select a relationship to inspect its evidence.</pre></div>"""


def graph_data(graph) -> dict:
    condensed = nx.condensation(graph.graph)
    groups = list(nx.topological_generations(condensed))
    nodes = []
    for level, components in enumerate(groups):
        ids = sorted(n for c in components for n in condensed.nodes[c]["members"])
        for row, node in enumerate(ids):
            attrs = dict(graph.nodes[node])
            attrs.update(x=20 + level * 300, y=20 + row * 85, source=graph.graph.in_degree(node) == 0)
            nodes.append(attrs)
    edges = [{"source": s, "target": t, "evidence": a["evidence"], "intermediates": a.get("intermediates", [])}
             for s, t, a in graph.graph.edges(data=True)]
    return {"nodes": nodes, "edges": edges}


def graph_html(graph) -> str:
    data = json.dumps(graph_data(graph), default=str).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>DataForge lineage</title><style>body{margin:20px}' + GRAPH_CSS + '</style></head><body>'
            '<h1>DataForge lineage</h1><p>Static dependencies with source evidence. Logical ordering is not execution order.</p>'
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
    return '<!doctype html><html lang="en"><meta charset="utf-8"><title>DataForge report</title><style>body{font:14px system-ui;margin:24px}table{border-collapse:collapse}td,th{padding:8px;border:1px solid #ccd;text-align:left;white-space:pre-wrap}</style><h1>DataForge report</h1><table><thead><tr>' + header + '</tr></thead><tbody>' + body + '</tbody></table></html>'


def source_bundle(store, file_ids: list[str]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for fid in dict.fromkeys(file_ids):
            source = store.file(fid)
            archive.writestr(safe_relative(source["relative_path"]), store.original(fid))
    return out.getvalue()
