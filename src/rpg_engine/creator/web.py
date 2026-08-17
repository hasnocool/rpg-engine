# ruff: noqa: E501
"""Dependency-free browser creator UI served by the local Creator Platform API."""

CREATOR_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RPG Engine Creator</title>
<style>
:root { color-scheme: dark; font-family: system-ui, sans-serif; }
body { margin: 0; background: #101317; color: #e7edf3; }
header { padding: 14px 18px; border-bottom: 1px solid #2b333d; display:flex; gap:14px; align-items:center; }
main { display:grid; grid-template-columns: 230px minmax(420px,1fr) minmax(360px,1fr); height:calc(100vh - 58px); }
.panel { padding: 12px; overflow:auto; border-right:1px solid #2b333d; }
button, select, input, textarea { background:#171d24; color:#e7edf3; border:1px solid #394553; border-radius:5px; padding:7px; }
button { cursor:pointer; } button:hover { background:#222b35; }
textarea { width:100%; min-height:430px; box-sizing:border-box; font-family:ui-monospace,monospace; resize:vertical; }
.resource { padding:7px; border-bottom:1px solid #252d36; cursor:pointer; }
.resource:hover { background:#171d24; }
.row { display:flex; gap:7px; margin:7px 0; align-items:center; }
.row > input, .row > select { flex:1; }
#error { color:#ff9191; white-space:pre-wrap; }
#status { color:#94dda8; white-space:pre-wrap; }
#lint { white-space:pre-wrap; font-family:ui-monospace,monospace; font-size:12px; }
svg { width:100%; height:430px; background:#0b0e12; border:1px solid #394553; border-radius:5px; touch-action:none; }
.edge { stroke:#667789; stroke-width:2; } .node { fill:#293747; stroke:#9db5cc; stroke-width:2; cursor:grab; }
.node-label { fill:#fff; font-size:12px; pointer-events:none; text-anchor:middle; }
h3 { margin:8px 0; }
small { color:#aeb9c4; }
</style>
</head>
<body>
<header><strong>RPG Engine Creator v0.9</strong><span id="pack"></span><button onclick="validatePack()">Validate</button></header>
<main>
<section class="panel">
  <h3>Resources</h3>
  <select id="kind" onchange="loadResources()"></select>
  <div class="row"><input id="new-id" placeholder="resource_id"><button onclick="newResource()">New</button></div>
  <div id="resources"></div>
</section>
<section class="panel">
  <h3 id="editor-title">Editor</h3>
  <small>Schema-validated JSON; saved as canonical YAML.</small>
  <textarea id="editor" spellcheck="false"></textarea>
  <div class="row"><button onclick="saveResource()">Save</button><button onclick="deleteResource()">Delete</button></div>
  <div id="error"></div><div id="status"></div>
  <h3>Validation</h3><div id="lint"></div>
</section>
<section class="panel">
  <h3>Map graph</h3>
  <small>Drag locations to arrange the creator-only layout. Logical topology stays in connection YAML.</small>
  <svg id="map" viewBox="0 0 700 430"></svg>
  <div class="row"><button onclick="loadMap()">Refresh map</button><button onclick="saveLayout()">Save layout</button></div>
</section>
</main>
<script>
const api='/api/creator/v1'; let current=null; let schemas={}; let graph={nodes:[],edges:[]}; let layout={positions:{}};
async function request(url, options={}) { const r=await fetch(url,options); const t=await r.text(); let data={}; try{data=t?JSON.parse(t):{};}catch{data={detail:t};} if(!r.ok) throw new Error(data.detail||t||r.statusText); return data; }
function showError(e){document.getElementById('error').textContent=String(e);}
function clearMessages(){document.getElementById('error').textContent='';document.getElementById('status').textContent='';}
async function boot(){
  try{
    const info=await request(api+'/info'); document.getElementById('pack').textContent=`${info.pack_id} ${info.pack_version}`;
    schemas=await request(api+'/schemas'); const sel=document.getElementById('kind');
    Object.keys(schemas.resources).forEach(k=>{const o=document.createElement('option');o.value=k;o.textContent=schemas.resources[k].title;sel.appendChild(o);});
    await loadResources(); await loadMap();
  }catch(e){showError(e);}
}
async function loadResources(){
  clearMessages(); const kind=document.getElementById('kind').value; const records=await request(`${api}/resources?kind=${encodeURIComponent(kind)}`);
  const box=document.getElementById('resources'); box.innerHTML=''; records.forEach(r=>{const d=document.createElement('div');d.className='resource';d.textContent=`${r.name||r.id} [${r.id}]`;d.onclick=()=>openResource(kind,r.id);box.appendChild(d);});
}
async function openResource(kind,id){
  clearMessages(); const r=await request(`${api}/resources/${kind}/${encodeURIComponent(id)}`); current={kind,id};
  document.getElementById('editor-title').textContent=`${kind}: ${id}`;document.getElementById('editor').value=JSON.stringify(r.payload,null,2);
}
async function newResource(){
  clearMessages(); const kind=document.getElementById('kind').value,id=document.getElementById('new-id').value.trim(); if(!id)return;
  try{const r=await request(`${api}/resources/${kind}/${encodeURIComponent(id)}/template`,{method:'POST'});await loadResources();await openResource(kind,r.id);}catch(e){showError(e);}
}
async function saveResource(){
  if(!current)return; clearMessages(); try{const body=JSON.parse(document.getElementById('editor').value);await request(`${api}/resources/${current.kind}/${encodeURIComponent(current.id)}`,{method:'PUT',headers:{'content-type':'application/json'},body:JSON.stringify(body)});document.getElementById('status').textContent='Saved.';await loadResources();await loadMap();}catch(e){showError(e);}
}
async function deleteResource(){
  if(!current||!confirm(`Delete ${current.kind}/${current.id}?`))return; clearMessages();try{await request(`${api}/resources/${current.kind}/${encodeURIComponent(current.id)}`,{method:'DELETE'});current=null;document.getElementById('editor').value='';await loadResources();await loadMap();}catch(e){showError(e);}
}
async function validatePack(){
  clearMessages(); try{const r=await request(api+'/validate',{method:'POST'});const lines=[`valid=${r.valid}`, ...r.issues.map(i=>`${i.severity.toUpperCase()} ${i.code}: ${i.message}${i.path?' ('+i.path+')':''}`)];document.getElementById('lint').textContent=lines.join('\n');}catch(e){showError(e);}
}
function pointFor(node,i){const p=layout.positions[node.id];return p?{x:p.x,y:p.y}:{x:90+(i%4)*165,y:70+Math.floor(i/4)*120};}
function renderMap(){
  const svg=document.getElementById('map');svg.innerHTML='';const points={};graph.nodes.forEach((n,i)=>points[n.id]=pointFor(n,i));
  graph.edges.forEach(e=>{const a=points[e.from_location_id],b=points[e.to_location_id];if(!a||!b)return;const line=document.createElementNS('http://www.w3.org/2000/svg','line');line.setAttribute('class','edge');line.setAttribute('x1',a.x);line.setAttribute('y1',a.y);line.setAttribute('x2',b.x);line.setAttribute('y2',b.y);svg.appendChild(line);});
  graph.nodes.forEach((n,i)=>{const p=points[n.id];const g=document.createElementNS('http://www.w3.org/2000/svg','g');g.dataset.id=n.id;g.setAttribute('transform',`translate(${p.x},${p.y})`);const c=document.createElementNS('http://www.w3.org/2000/svg','circle');c.setAttribute('r','28');c.setAttribute('class','node');const t=document.createElementNS('http://www.w3.org/2000/svg','text');t.setAttribute('class','node-label');t.setAttribute('y','4');t.textContent=n.name.slice(0,16);g.append(c,t);svg.appendChild(g);g.addEventListener('pointerdown',ev=>startDrag(ev,g));});
}
let drag=null;function startDrag(ev,g){g.setPointerCapture(ev.pointerId);drag={g,id:g.dataset.id};g.onpointermove=moveDrag;g.onpointerup=endDrag;}
function moveDrag(ev){if(!drag)return;const svg=document.getElementById('map'),pt=svg.createSVGPoint();pt.x=ev.clientX;pt.y=ev.clientY;const p=pt.matrixTransform(svg.getScreenCTM().inverse());layout.positions[drag.id]={x:p.x,y:p.y};drag.g.setAttribute('transform',`translate(${p.x},${p.y})`);}
function endDrag(){drag=null;renderMap();}
async function loadMap(){try{const data=await request(api+'/map');graph=data.graph;layout=data.layout;renderMap();}catch(e){showError(e);}}
async function saveLayout(){try{await request(api+'/map/layout',{method:'PUT',headers:{'content-type':'application/json'},body:JSON.stringify(layout)});document.getElementById('status').textContent='Map layout saved.';}catch(e){showError(e);}}
boot();
</script>
</body></html>'''
