'use strict';
const $=s=>document.getElementById(s), demo=window.CASSIE_PREVIEW||null;
const el=(tag,value='',cls='')=>{const n=document.createElement(tag);n.textContent=value;if(cls)n.className=cls;return n;};
let token='', page='command', live=null, notes=[], catalog=[], topic='', more=10, simulated='nominal', expression='nominal', busy=false;
let camera=null,cameraRun=0,cameraBusy=false,mic=null,listening=false,audio=null,spoken=false,conversationUntil=0;
let lastScene='',lastSceneAt=0,toastStop=0,catalogInfo=null,clearing=false;
let alwaysEnabled=false,alwaysBusy=false,alwaysPoll=false,alwaysEpoch=0,observerStream=null;
let chatAbort=null,micRequest=null,micEpoch=0,micStarting=false,recording=false;
const CONVERSATION_MS=45_000;
function toast(value){$('toast').textContent=value;clearTimeout(toastStop);toastStop=setTimeout(()=>$('toast').textContent='',5200);}
async function api(path,data,signal){
  const opts={headers:{Authorization:'Bearer '+token},signal};
  if(data!==undefined){opts.method='POST';opts.headers['Content-Type']='application/json';opts.body=JSON.stringify(data);}
  const r=await fetch('/api/'+path,opts), j=await r.json();
  if(!r.ok)throw new Error(j.error||'CASSIE could not complete that request.');
  return j;
}
const states={
 nominal:['◉','Nominal','Systems ready · awaiting input','00','Standing by.','No active Sentinel alerts in this scenario.',[62,128,255]],
 omega:['Ω','Omega Red','Critical integrity alert · review containment','01','Integrity check failed','Demo: an integrity failure needs operator review. Nothing was quarantined or deleted.',[250,66,84]],
 delta:['Δ','Delta Yellow','Device presence changed · review network','02','Network change observed','Demo: a new device appeared on CASSIE-NET, and a watched device is missing.',[252,180,63]],
 gamma:['γ','Gamma Green','Persona expression · happy','03','Happy expression','“Everything’s behaving today. Frankly, I’m suspicious.”',[57,224,149]]
};
let color=[62,128,255];
function status(){
  const omega=demo?simulated==='omega':live?.integrity?.state==='critical';
  const delta=demo?simulated==='delta':(!live?.network?.error&&!!live?.network?.devices?.some(d=>d.state==='new'||d.state==='missing'));
  const gamma=(demo?simulated:expression)==='gamma';
  const state=omega?'omega':delta?'delta':gamma?'gamma':'nominal';
  const [icon,title,detail,code,signal,description,tint]=states[state];
  color=tint;$('presence').dataset.state=state;$('orb-indicator').textContent=icon;$('orb-title').textContent=title;
  $('orb-text').textContent=demo||live?detail:'Waiting for the local service';$('orb-tag').textContent='STATE / '+code;
  $('s-omega').textContent=omega?'ACTIVE':demo||live?.integrity?.state==='ok'?'CLEAR':'UNVERIFIED';
  $('s-delta').textContent=delta?'ACTIVE':demo||live?.network?.configured&&!live?.network?.error?'CLEAR':'UNVERIFIED';
  $('s-gamma').textContent=gamma?'HAPPY':'CALM';
  $('signal-title').textContent=!demo&&!live?'Awaiting a reading':signal;
  $('signal-text').textContent=demo?description:!live?'The console hasn’t read the system yet.':
    omega?live.integrity.detail:delta?'Review new and missing neighbors in Network.':gamma?description:
    live.integrity.state==='unknown'?live.integrity.detail:'Latest local integrity check passed. Open System modules for readings.';
  document.querySelectorAll('#scenarios button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.state===simulated)));
  if(reduced.matches)drawOrb(0);
}
const reduced=matchMedia('(prefers-reduced-motion: reduce)'), orb=$('orb'), ctx=orb.getContext('2d');
let seed=8127;
const rnd=()=>{seed=(Math.imul(1664525,seed)+1013904223)>>>0;return seed/4294967296;};
const points=Array.from({length:6100},()=>{const z=2*rnd()-1,a=rnd()*Math.PI*2,r=Math.sqrt(1-z*z);return [Math.cos(a)*r,Math.sin(a)*r,z,.82+.23*rnd(),rnd(),rnd()];});
function drawOrb(ms){
  if(!ctx||!orb.clientWidth||!orb.clientHeight)return;
  const w=orb.clientWidth,h=orb.clientHeight,dpr=Math.min(devicePixelRatio||1,2),t=ms/1000;
  if(orb.width!==Math.round(w*dpr)||orb.height!==Math.round(h*dpr)){orb.width=Math.round(w*dpr);orb.height=Math.round(h*dpr);}
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
  const x0=w*.5,y0=h*.475,R=Math.min(w*.29,h*.35), rgb=color.join(',');
  const haze=ctx.createRadialGradient(x0,y0,3,x0,y0,R*1.64);
  haze.addColorStop(0,'rgba('+rgb+',.19)');haze.addColorStop(.61,'rgba('+rgb+',.09)');haze.addColorStop(1,'rgba('+rgb+',0)');
  ctx.fillStyle=haze;ctx.fillRect(0,0,w,h);
  ctx.setLineDash([3,8]);ctx.strokeStyle='rgba('+rgb+',.29)';ctx.lineWidth=1;
  for(const scale of [1.23,1.47]){ctx.beginPath();ctx.ellipse(x0,y0,R*scale,R*scale*.92,-.17,0,Math.PI*2);ctx.stroke();}
  ctx.setLineDash([]);ctx.strokeStyle='rgba('+rgb+',.12)';ctx.beginPath();ctx.moveTo(x0-R*1.65,y0);ctx.lineTo(x0+R*1.65,y0);ctx.moveTo(x0,y0-R*1.35);ctx.lineTo(x0,y0+R*1.35);ctx.stroke();
  const ca=Math.cos(t*.19),sa=Math.sin(t*.19);
  const tiers=Array.from({length:12},()=>[]);
  for(const [x,y,z,rad,size,spark] of points){
    const ax=x*ca-z*sa,az=z*ca+x*sa,by=y*.96+az*.28,bz=az*.96-y*.28;
    const swell=rad+(Math.sin(x*5.5+y*4+z*3+t*1.25)+Math.sin(y*8-z*3-t*.8))*.095;
    const light=.14+.38*Math.max(0,bz)+.24*spark+.24*Math.max(0,Math.sin(8*y+4*x+t*1.15))*Math.max(0,bz+.15);
    const step=Math.max(2,R*.023),px=Math.round((x0+ax*R*swell*(1+bz*.07))/step)*step,py=Math.round((y0+by*R*swell*(1+bz*.07))/step)*step;
    tiers[Math.min(11,Math.floor(light*12))].push([px,py,Math.min(step-.4,.8+size*step*.62)]);
  }
  for(let i=0;i<tiers.length;i++){
    const ratio=.44+i*.08;ctx.fillStyle='rgba('+color.map(v=>Math.min(255,Math.round(v*ratio+Math.max(0,i-8)*20))).join(',')+','+(.12+i*.065)+')';
    for(const [x,y,s] of tiers[i])ctx.fillRect(x,y,s,s);
  }
  ctx.font='9px monospace';ctx.fillStyle='rgba('+rgb+',.48)';
  if(w>430){ctx.fillText('CORE / 001',17,32);ctx.textAlign='right';ctx.fillText('SIGNAL FIELD',w-17,h-23);ctx.textAlign='left';}
}
let lastDraw=-100;
function animate(t){if(!reduced.matches&&page==='command'&&!document.hidden&&t-lastDraw>(token||demo?32:180)){drawOrb(t);lastDraw=t;}requestAnimationFrame(animate);}
requestAnimationFrame(animate); new ResizeObserver(()=>{if(reduced.matches)drawOrb(0);}).observe(orb);
reduced.addEventListener('change',()=>{if(reduced.matches)drawOrb(0);});
function setPage(value){
  if(!document.getElementById(value)?.classList.contains('page'))return;
  page=value;
  document.querySelectorAll('.page').forEach(n=>n.hidden=n.id!==value);
  document.querySelectorAll('.nav').forEach(n=>{const active=n.dataset.page===value;n.classList.toggle('current',active);if(active)n.setAttribute('aria-current','page');else n.removeAttribute('aria-current');if(active)$('crumb').textContent=n.childNodes[1].textContent.trim();});
  if(value!=='awareness'&&camera){cameraController?.abort();stopCamera();}
  placeObserver();
  if(value==='knowledge')renderKnowledge();
  if(value==='workshop')loadInbox();
  if(value==='command'&&reduced.matches)drawOrb(0);
  scrollTo(0,0);
}
document.querySelectorAll('[data-page],[data-jump]').forEach(n=>n.onclick=()=>setPage(n.dataset.page||n.dataset.jump));
document.querySelectorAll('[data-state]:is(button)').forEach(b=>b.onclick=()=>{if(demo)simulated=b.dataset.state;else expression=b.dataset.state;status();});
function link(title,url){
  try{const u=new URL(url);if(!['https:','http:'].includes(u.protocol)||u.username||u.password)return el('span',title);
    const a=el('a',title+' ↗');a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';return a;
  }catch{return el('span',title);}
}
function message(text,role='assistant',sources=[]){
  const row=el('div','','message '+role);row.append(el('b',role==='user'?'YOU':'CASSIE'),document.createTextNode(text));
  for(const s of sources)row.append(el('br'),link(s.title,s.url));$('chat-log').append(row);
  $('chat-log').scrollTop=$('chat-log').scrollHeight;
}
function* speechChunks(text){
  const characters=Array.from(text);
  for(let start=0;start<characters.length;){
    let end=Math.min(start+650,characters.length);
    if(end<characters.length){
      let boundary=end;
      while(boundary>start&&!/\s/.test(characters[boundary-1]))boundary--;
      if(boundary>start)end=boundary;
    }
    const part=characters.slice(start,end).join('');
    if(part.trim())yield part;
    start=end;
  }
}
async function speak(text){
  if(demo){toast('Voice is simulated in this offline preview.');return;}
  if(!token||spoken)return;
  spoken=true;pauseMic(true);
  try{
    for(const part of speechChunks(text)){
      if(!spoken||!token)return;
      const response=await api('voice',{text:part},AbortSignal.timeout(15000));
      if(!spoken||!token)return;
      const raw=Uint8Array.from(atob(response.wav),c=>c.charCodeAt(0)),url=URL.createObjectURL(new Blob([raw],{type:'audio/wav'}));
      try{
        const next=new Audio(url);audio=next;
        await new Promise((resolve,reject)=>{
          next.onended=resolve;next.onerror=()=>reject(new Error('CASSIE could not play the reply.'));
          next.play().catch(reject);
        });
      }finally{URL.revokeObjectURL(url);}
    }
  }catch(e){toast(e.message);}
  finally{audio=null;spoken=false;pauseMic(false);}
}
async function streamChat(text, signal, update, voice, useCamera){
  const response=await fetch('/api/chat',{
    method:'POST',signal,headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},
    body:JSON.stringify({text,voice,use_camera:useCamera,stream:true,include_status:/\b(system|gpu|storage|network|diagnos)\w*/i.test(text)})
  });
  if(!response.ok){const result=await response.json();throw new Error(result.error||'CASSIE could not accept the message.');}
  const reader=response.body.pipeThrough(new TextDecoderStream()).getReader();
  let pending='';
  try{
    for(;;){
      const {value,done}=await reader.read();
      if(done)throw new Error('The local connection closed before CASSIE finished.');
      const lines=(pending+value).split('\n');pending=lines.pop();
      for(const line of lines){
        if(!line)continue;
        const event=JSON.parse(line);
        if(event.error)throw new Error(event.error);
        if(event.reply)return event.reply;
        if(event.delta)update(event.delta);
      }
    }
  }finally{await reader.cancel().catch(()=>{});}
}
async function send(text, voice=false, useCamera=false){
  if(!text.trim()||busy||clearing||$('clear-dialog').open||(!demo&&!token))return;
  if(/^(?:please )?(?:clear|reset|delete) (?:(?:the|this|my) )?(?:chat(?: history)?|conversation)[.!? ]*$/i.test(text.trim())){
    openClearDialog();
    if(voice)await speak('Confirm on the screen to clear this conversation.');
    return;
  }
  const controller=new AbortController();
  chatAbort=controller;busy=true;
  if(voice)setVoiceStatus('Thinking…');$('message').value='';$('send').disabled=true;message(text,'user');
  const row=el('div','','message assistant'), reply=el('span','Thinking…','chat-thinking');
  row.append(el('b','CASSIE'),reply);$('chat-log').append(row);$('chat-log').scrollTop=$('chat-log').scrollHeight;
  let partial='';
  try{
    let result;
    if(demo){
      const canned=simulated==='omega'?'Red means check the evidence first. I’d isolate the affected component and keep the original for inspection.':
        /network|device|wifi/i.test(text)?'I’d look at CASSIE-NET’s authorized device list. If your phone’s playing hide-and-seek, we’ll check when it was last observed.':
        /data|source|research/i.test(text)?'Try the Knowledge web. Pick a topic and I’ll show you what’s in the catalog. I’ll even resist calling it a rabbit hole.':
        'I’m here. Pick a module or ask me about the network. I can do dramatic lighting and practical advice at the same time.';
      result={content:canned,sources:[]};
    }else result=await streamChat(text,controller.signal,delta=>{
      partial+=delta;reply.textContent=partial;reply.classList.remove('chat-thinking');
      $('chat-log').scrollTop=$('chat-log').scrollHeight;
    },voice,useCamera);
    if(controller.signal.aborted)return;
    reply.textContent=result.content;reply.classList.remove('chat-thinking');
    for(const source of result.sources||[])row.append(el('br'),link(source.title,source.url));
    if(result.used_camera)row.append(el('small','Live camera frame','reply-camera'));
    if(result.memory_changed)void api('session').then(session=>{if(token&&!controller.signal.aborted){notes=session.notes;}}).catch(()=>{});
    $('chat-log').scrollTop=$('chat-log').scrollHeight;
    if(voice||result.verbatim||$('speak').checked)await speak(result.content);
  }catch(error){
    if(!controller.signal.aborted){
      reply.textContent=(partial?partial+'\n\n':'')+error.message;
      reply.className='chat-error';
      if(voice)await speak('Titan, the local model didn’t answer. The dashboard has the error.');
    }
  }finally{
    if(chatAbort===controller){
      if(voice&&listening){conversationUntil=Date.now()+CONVERSATION_MS;setVoiceStatus('Listening for your follow-up.');}
      chatAbort=null;busy=false;$('send').disabled=false;micControls();
    }
  }
}
$('chat-form').onsubmit=e=>{e.preventDefault();send($('message').value);};
const moduleRows=[
 ['DSM / 01','Data storage',v=>v.ssd+' SSD free',v=>v.bulk+' Critical files stay on the system volume.'],
 ['DSM / 02','Memory cache',v=>v.ram,v=>'Available RAM and total RAM. The OS manages its own file cache.'],
 ['PAS / 03','Public address',v=>v.voice?'Voice available':'Voice dependency unavailable',v=>'Local English speech output. Microphone status is shown under Awareness.'],
 ['DMM / 04','Decision-making',v=>v.model?'Local model online':'Local model offline',v=>v.gpu+' Model answers stay on TitanGame.'],
 ['HDM / 05','Hardware diagnostics',v=>v.integrity,v=>v.hdm+' CPU load: '+v.load+' · Temperature: '+v.temperature],
 ['SMH / 06','Standby handlers',v=>v.model?'Model on demand':'Model unavailable',v=>'Systemd can restart services after a failure. The model unloads after five idle minutes. Both services share this host.']
];
function modules(){
 const m=live?.machine||{}, gb=x=>x==null?'—':x+' GiB';
 const v={ssd:gb(m.storage_free_gib),bulk:live?.bulk?.mounted?gb(live.bulk.free_gib)+' free on mounted bulk drive.':'Bulk drive not mounted.',
 ram:gb(m.ram_available_gib)+' / '+gb(m.ram_total_gib),voice:live?.voice,model:m.model_ready,
 load:m.load_1min??'—',temperature:m.cpu_c==null?'unavailable':m.cpu_c+' °C',
 gpu:m.gpu?.length?m.gpu.map(g=>g.name+' · '+g.used_mib+' / '+g.total_mib+' MiB VRAM.').join(' '):'No NVIDIA reading.',
 integrity:live?.integrity?.state==='ok'?'Integrity check passed':live?.integrity?.state==='critical'?'Integrity failure':'Awaiting integrity check',
 hdm:(live?.integrity?.detail||'Waiting for a local reading.')+
     (m.storage_free_gib!=null&&m.storage_free_gib<5?' Less than 5 GiB free: move bulk files to a mounted archive before adding more.':'')};
 $('module-grid').replaceChildren(...moduleRows.map(([code,name,metric,desc])=>{const box=el('section','','panel padded module');box.append(el('p',code,'kicker'),el('h2',name),el('p',metric(v),'metric'),el('p',desc(v)));return box;}));
 $('mini-modules').replaceChildren(...[['DSM · Storage',v.ssd+' free'],['DMM · Local model',v.model?'READY':'OFFLINE'],['HDM · Integrity',v.integrity],['PAS · Microphone',listening?'WAKE LISTENING':'OFF']].map(([a,b])=>{const d=el('div','','mini');d.append(el('span',a),el('strong',b));return d;}));
}
function network(){
 const n=live?.network;
 $('network-status').textContent=demo?'SIMULATED':n?.error?'READ FAILED':n?.configured?'MONITORING':'UNCONFIGURED';
 const list=$('network-list');list.replaceChildren();
 if(!n?.configured||n.error){list.append(el('p',n?.error||'Set a dedicated CASSIE-NET hotspot interface on TitanGame before enabling neighbor monitoring.'));return;}
 if(!n.devices.length){list.append(el('p','No neighbors observed yet. A quiet device can go unseen; this is not a definitive connected-client list.'));return;}
 for(const d of n.devices){
   const row=el('div','','network-item');row.append(el('strong',d.name||d.ip),el('span',d.mac+' · '+d.state+' · '+(d.last_seen?new Date(d.last_seen*1000).toLocaleString():'no recent observation')));
   if(!demo){const b=el('button',d.watched?'Stop watching':'Watch for absence','quiet');b.onclick=async()=>{try{await api('watch',{mac:d.mac,watched:!d.watched});await refresh();}catch(e){toast(e.message);}};row.append(b);}
   list.append(row);
 }
}
let refreshing=false;
async function refresh(){
 if((!demo&&!token)||refreshing)return;const session=token;refreshing=true;
 try{const result=demo?demo.telemetry:await api('command');if(session!==token)return;live=result;status();modules();network();}
 catch(e){if(!token)return;live=null;status();modules();network();toast(e.message);}
 finally{refreshing=false;}
}
$('refresh').onclick=refresh;
const NS='http://www.w3.org/2000/svg';
function svg(name,attrs){const n=document.createElementNS(NS,name);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);return n;}
const graph=$('graph'),graphNodes=new Map();
let graphLayer=null,graphTopicKey='',graphDrag=null,graphMotion=0;
let graphView={x:0,y:0,scale:1};

function paintGraph(){
 graphLayer?.setAttribute('transform','translate('+graphView.x+' '+graphView.y+') scale('+graphView.scale+')');
 if(graphLayer)graphLayer.classList.toggle('zoomed',graphView.scale>=1.7);
}
function graphPoint(event){
 return new DOMPoint(event.clientX,event.clientY).matrixTransform(graph.getScreenCTM().inverse());
}
function moveGraph(destination, animate=true){
 cancelAnimationFrame(graphMotion);
 if(!animate||reduced.matches){graphView=destination;paintGraph();return;}
 const start={...graphView}, time=performance.now();
 const tick=now=>{
  const t=1-Math.pow(1-Math.min(1,(now-time)/190),3);
  graphView={x:start.x+(destination.x-start.x)*t,y:start.y+(destination.y-start.y)*t,
    scale:start.scale+(destination.scale-start.scale)*t};
  paintGraph();
  if(t<1)graphMotion=requestAnimationFrame(tick);
 };
 graphMotion=requestAnimationFrame(tick);
}
function zoomGraph(factor,point={x:320,y:192},animate=true){
 const scale=Math.min(3.6,Math.max(.65,graphView.scale*factor));
 const ratio=scale/graphView.scale;
 moveGraph({scale,x:point.x-(point.x-graphView.x)*ratio,y:point.y-(point.y-graphView.y)*ratio},animate);
}
function placeNode(node){
 node.group.setAttribute('transform','translate('+node.x+' '+node.y+')');
 node.edge.setAttribute('x2',node.x);node.edge.setAttribute('y2',node.y);
}
function chooseTopic(name){
 if(name!==topic){$('topic-filter').value='';more=10;}
 topic=name;renderKnowledge();
}
function drawKnowledge(topics){
 const key=topics.join('\n');
 if(graphLayer?.isConnected&&key===graphTopicKey)return;
 graphTopicKey=key;graphNodes.clear();
 graphLayer=svg('g',{class:'map-world'});
 const edges=svg('g',{}),nodes=svg('g',{});
 graphLayer.append(edges,svg('circle',{cx:320,cy:192,r:35,class:'map-core'}),
   Object.assign(svg('text',{x:320,y:196,'text-anchor':'middle',class:'core-label'}),{textContent:'CASSIE'}),nodes);
 for(const [ring,group] of [topics.slice(0,11),topics.slice(11)].entries()){
  for(const [index,name] of group.entries()){
   const angle=-Math.PI/2+(index+(ring?.25:0))*2*Math.PI/group.length;
   const count=name==='Owner memory'?notes.length:catalog.filter(row=>row[0]===name).length;
   const node={
    x:320+(ring?232:128)*Math.cos(angle),y:192+(ring?150:79)*Math.sin(angle),
    group:svg('g',{class:'node '+(name==='Owner memory'?'note-node':''),'data-topic':name,
                   'aria-label':name,role:'button',tabindex:'0'}),
    edge:svg('line',{x1:320,y1:192,x2:320,y2:192,class:'edge'})
   };
   const title=svg('title',{});title.textContent=name+' · '+count+(name==='Owner memory'?' notes':' datasets');
   const label=svg('text',{x:12,y:4,class:'map-label'});label.textContent=name;
   if(node.x>490){label.setAttribute('x','-12');label.setAttribute('text-anchor','end');}
   node.group.append(title,svg('circle',{r:14,class:'node-hit'}),svg('circle',{r:5,class:'node-dot'}),label);
   node.group.onkeydown=event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();chooseTopic(name);}};
   edges.append(node.edge);nodes.append(node.group);graphNodes.set(name,node);placeNode(node);
  }
 }
 graph.replaceChildren(graphLayer);paintGraph();
}
graph.addEventListener('wheel',event=>{
 event.preventDefault();zoomGraph(Math.exp(-event.deltaY*.0018),graphPoint(event),false);
},{passive:false});
graph.onpointerdown=event=>{
 if(event.button!==0||graphDrag)return;
 cancelAnimationFrame(graphMotion);
 const name=event.target.closest('.node')?.dataset.topic,node=graphNodes.get(name),point=graphPoint(event);
 graphDrag={id:event.pointerId,name,node,point,x:node?.x??graphView.x,y:node?.y??graphView.y,moved:false};
 graph.setPointerCapture(event.pointerId);
};
graph.onpointermove=event=>{
 if(graphDrag?.id!==event.pointerId)return;
 const drag=graphDrag,point=graphPoint(event);
 const dx=point.x-drag.point.x,dy=point.y-drag.point.y;
 if(!drag.moved&&Math.hypot(dx,dy)<5)return;
 drag.moved=true;graph.classList.add('dragging');
 if(drag.node){
  drag.node.x=drag.x+dx/graphView.scale;drag.node.y=drag.y+dy/graphView.scale;placeNode(drag.node);
 }else{
  moveGraph({...graphView,x:drag.x+dx,y:drag.y+dy},false);
 }
};
function finishGraphDrag(event){
 if(graphDrag?.id!==event.pointerId)return;
 const drag=graphDrag;graphDrag=null;graph.classList.remove('dragging');
 if(event.type==='pointerup'&&!drag.moved&&drag.name){
  drag.node.group.focus();chooseTopic(drag.name);
 }
}
graph.onpointerup=graph.onpointercancel=graph.onlostpointercapture=finishGraphDrag;
$('graph-zoom-in').onclick=()=>zoomGraph(1.3);
$('graph-zoom-out').onclick=()=>zoomGraph(1/1.3);
$('graph-reset').onclick=()=>{
 graphLayer=null;
 renderKnowledge();moveGraph({x:0,y:0,scale:1});
};
function renderKnowledge(){
 const topics=[...new Set(catalog.map(r=>r[0]))].sort();
 if(notes.length||!topics.length)topics.push('Owner memory');
 if(!topics.includes(topic))topic=topics.includes('Machine Learning')?'Machine Learning':topics[0];
 if(graphTopicKey!==topics.join('\n')||!$('topic').options.length){
  $('topic').replaceChildren(...topics.map(t=>{const o=el('option',t);o.value=t;return o;}));
 }
 $('topic').value=topic;$('map-info').textContent=catalog.length+(catalogInfo?' searchable local listings':' catalog links')+' · '+topics.filter(t=>t!=='Owner memory').length+' topics · '+notes.length+' owner notes';
 $('map-info').title=catalogInfo?catalogInfo.total+' indexed · '+catalogInfo.flagged+' flagged by the source':'';
 drawKnowledge(topics);
 for(const [name,node] of graphNodes){
  const selected=name===topic;
  node.group.classList.toggle('active',selected);node.edge.classList.toggle('active',selected);
  node.group.setAttribute('aria-pressed',String(selected));
 }
 $('topic-heading').textContent=topic;
 const q=$('topic-filter').value.trim().toLowerCase();
 let rows=topic==='Owner memory'?notes.filter(n=>n.note.toLowerCase().includes(q)):catalog.filter(r=>r[0]===topic&&(r[1]+' '+r[2]).toLowerCase().includes(q));
 const section=$('datasets');section.replaceChildren();
 if(!rows.length)section.append(el('p','Nothing matches here yet.','data-entry'));
 for(const data of rows.slice(0,more)){
  const n=el('div','','data-entry');
  if(topic==='Owner memory'){n.append(el('strong',data.note),el('small','Owner note'));
   const b=el('button','Remove note','quiet');b.onclick=async()=>{if(!confirm('Remove this saved note?'))return;try{notes=demo?notes.filter(x=>x.id!==data.id):(await api('memory/remove',{id:data.id})).notes;renderKnowledge();}catch(e){toast(e.message);}};n.append(b);
  }else n.append(link(data[1],data[3]),el('small',data[2]||'Public catalog link'));
  section.append(n);
 }
 $('next-data').hidden=rows.length<=more;
}
$('topic').onchange=e=>chooseTopic(e.target.value);
$('topic-filter').oninput=()=>{more=10;renderKnowledge();};
$('next-data').onclick=()=>{more+=10;renderKnowledge();};
$('note-form').onsubmit=async e=>{e.preventDefault();const note=$('note').value.trim();if(!note)return;
 try{notes=demo?[{id:Date.now(),note},...notes]:(await api('memory',{note})).notes;$('note').value='';topic='Owner memory';renderKnowledge();toast(demo?'Added to this preview session.':'Saved to local owner memory.');}catch(error){toast(error.message);}
};
function stopCamera(){
 cameraRun++;camera?.getTracks?.().forEach(t=>t.stop());camera=null;$('camera').srcObject=null;$('camera').hidden=true;$('camera-idle').hidden=false;$('camera-mock').hidden=true;$('boxes').replaceChildren();
 $('camera-toggle').textContent='Start camera';$('camera-status').textContent='Camera is off.';$('observation').textContent='';
}
function placeObserver(){
 const slot=$(page==='awareness'?'always-slot':'always-home'),dock=$('always-dock');
 if(dock.parentNode!==slot)slot.append(dock);
}
function clearObserverFrame(){
 observerStream?.abort();observerStream=null;
 const canvas=$('always-image');
 canvas.width=0;canvas.height=0;canvas.hidden=true;
}
async function streamObserver(){
 if(observerStream||!token||document.hidden)return;
 const controller=new AbortController(),canvas=$('always-image');
 observerStream=controller;
 let reader;
 try{
  const response=await fetch('/api/camera/stream',{
    headers:{Authorization:'Bearer '+token},signal:controller.signal
  });
  if(!response.ok)throw new Error('Camera stream unavailable.');
  reader=response.body.getReader();
  let pending=new Uint8Array(0);
  for(;;){
   const {value,done}=await reader.read();
   if(done||controller.signal.aborted)break;
   const chunk=new Uint8Array(pending.length+value.length);
   chunk.set(pending);chunk.set(value,pending.length);
   const header=new DataView(chunk.buffer);
   let offset=0,latest=null;
   while(chunk.length-offset>=4){
    const size=header.getUint32(offset);
    if(size>1_000_000)throw new Error('Invalid local camera frame.');
    if(chunk.length-offset<4+size)break;
    if(size)latest=chunk.subarray(offset+4,offset+4+size);
    offset+=4+size;
   }
   pending=chunk.slice(offset);
   if(!latest)continue;
   const bitmap=await createImageBitmap(new Blob([latest],{type:'image/jpeg'}));
   try{
    if(controller.signal.aborted)break;
    if(canvas.width!==bitmap.width||canvas.height!==bitmap.height){
     canvas.width=bitmap.width;canvas.height=bitmap.height;
    }
    canvas.getContext('2d',{alpha:false}).drawImage(bitmap,0,0);
    canvas.hidden=false;$('always-wait').hidden=true;
   }finally{bitmap.close();}
  }
 }catch(error){
  if(!controller.signal.aborted)$('always-wait').textContent=error.message;
 }finally{
  if(reader)await reader.cancel().catch(()=>{});
  if(observerStream===controller){clearObserverFrame();$('always-wait').hidden=false;}
 }
}
function showObserver(state){
 if(state.enabled&&!alwaysEnabled){cameraController?.abort();stopCamera();}
 alwaysEnabled=state.enabled;
 $('always-dock').hidden=!alwaysEnabled;
 $('camera-sight').hidden=!alwaysEnabled;
 $('camera-look').hidden=!state.sample;
 const detected=state.sample?[...new Set(state.sample.boxes.map(box=>box.label))]:[];
 $('camera-sight').textContent=detected.length?'In view: '+detected.join(', ')+'.':state.sample?'Camera is live. No confident object labels yet.':state.detail;
 $('always-start').hidden=alwaysEnabled||!token||!!demo;
 $('always-help').hidden=!token||!!demo;
 $('camera-frame').hidden=alwaysEnabled;
 $('camera-toggle').hidden=alwaysEnabled;
 $('detect-option').hidden=alwaysEnabled;
 $('camera-status').hidden=alwaysEnabled;
 $('always-dock').dataset.live=String(!!state.sample);
 $('always-state').textContent=state.sample
   ?state.detail.startsWith('Video is live.')?'Video live · detector unavailable':'Observing · '+state.sample.boxes.length+' outlined'
   :'Camera waiting';
 $('always-wait').textContent=state.detail;
 $('always-wait').hidden=!!state.sample&&!$('always-image').hidden;
 if(!state.sample){clearObserverFrame();return;}
 void streamObserver();
 const epoch=alwaysEpoch;
 void commentOnObjects(state.sample.boxes,()=>alwaysEnabled&&alwaysEpoch===epoch&&!!token);
}
async function pollObserver(){
 if(demo||!token||$('unlock').open||document.hidden||alwaysPoll||alwaysBusy)return;
 const epoch=alwaysEpoch;
 alwaysPoll=true;
 try{
  const state=await api('camera',undefined,AbortSignal.timeout(2500));
  if(epoch===alwaysEpoch&&token&&!document.hidden)showObserver(state);
 }catch{
  if(epoch===alwaysEpoch&&alwaysEnabled){
   showObserver({enabled:true,detail:'Waiting for the local camera service.'});
  }
 }finally{alwaysPoll=false;}
}
async function setObserver(enabled){
 if(demo||!token||alwaysBusy)return;
 const epoch=++alwaysEpoch;
 alwaysBusy=true;
 $('always-start').disabled=true;$('always-stop').disabled=true;
 if(enabled){cameraController?.abort();stopCamera();lastScene='';}
 try{
  const state=await api('camera',{enabled},AbortSignal.timeout(5000));
  if(epoch===alwaysEpoch&&token)showObserver(state);
  if(!enabled)$('observation').textContent='';
 }catch(e){if(epoch===alwaysEpoch&&token)toast(e.message);}
 finally{alwaysBusy=false;$('always-start').disabled=false;$('always-stop').disabled=false;}
}
$('always-start').onclick=()=>setObserver(true);
$('always-stop').onclick=()=>setObserver(false);
setInterval(pollObserver,650);
$('camera-toggle').onclick=async()=>{
 if(camera){cameraController?.abort();stopCamera();return;}
 if(demo){camera={};$('camera-mock').hidden=false;$('camera-idle').hidden=true;$('camera-toggle').textContent='Stop preview';
  $('camera-status').textContent='Simulated detection. This preview has not accessed your camera.';
  if($('commentary').checked)$('observation').textContent='“A mug and a laptop. Bold of you to let either get that close to the other.”';return;}
 const run=++cameraRun;lastScene='';
 try{const stream=await navigator.mediaDevices.getUserMedia({audio:false,video:{width:{ideal:640},height:{ideal:480}}});
  if(run!==cameraRun||page!=='awareness'||document.hidden||!token){stream.getTracks().forEach(t=>t.stop());return;}
  camera=stream;$('camera').srcObject=camera;$('camera').hidden=false;$('camera-idle').hidden=true;
  $('camera-toggle').textContent='Stop camera';$('camera-status').textContent='Local preview active.';
  camera.getVideoTracks()[0].onended=stopCamera;
 }catch(e){$('camera-status').textContent='Camera unavailable: '+e.message;}
};
let cameraController;
function rectangles(boxes){
 const v=$('camera'),w=v.clientWidth,h=v.clientHeight;
 const scale=Math.min(w/v.videoWidth,h/v.videoHeight),sW=v.videoWidth*scale,sH=v.videoHeight*scale;
 $('boxes').replaceChildren(...boxes.map(b=>{const box=el('div','','box');box.append(el('span',b.label+' '+Math.round(b.score*100)+'%'));const [x,y,right,bottom]=b.rect;
  Object.assign(box.style,{left:((w-sW)/2+x*sW)+'px',top:((h-sH)/2+y*sH)+'px',width:((right-x)*sW)+'px',height:((bottom-y)*sH)+'px'});return box;}));
}
async function commentOnObjects(boxes,isCurrent,signal){
 if(!$('commentary').checked||listening||busy)return;
 const types=[...new Set(boxes.map(b=>b.label).filter(l=>l!=='person'))].sort().join(', ');
 if(!types||types===lastScene||Date.now()-lastSceneAt<=45000)return;
 lastScene=types;lastSceneAt=Date.now();
 try{
  const r=await api('scene',{labels:types},signal);
  if(isCurrent()&&$('commentary').checked){
   $('observation').textContent=r.content;
   if($('speak').checked)await speak(r.content);
  }
 }catch(error){
  if(isCurrent()&&error.name!=='AbortError')$('observation').textContent='Comments paused while the model is unavailable or busy. Object detection continues.';
 }
}
setInterval(async()=>{
 if(demo||!camera||cameraBusy||page!=='awareness'||document.hidden||!token||!($('detect').checked||$('commentary').checked))return;
 const v=$('camera');if(!v.videoWidth)return;
 const canvas=document.createElement('canvas');canvas.width=Math.min(640,v.videoWidth);canvas.height=Math.round(v.videoHeight*canvas.width/v.videoWidth);
 canvas.getContext('2d').drawImage(v,0,0,canvas.width,canvas.height);
 const run=cameraRun;cameraBusy=true;cameraController=new AbortController();
 try{
  const frame=canvas.toDataURL('image/jpeg',.72).split(',')[1],answer=await api('detect',{image:frame},cameraController.signal);
  if(run!==cameraRun||!camera)return;
  if($('detect').checked)rectangles(answer.boxes);
  $('camera-status').textContent='Local detection active · '+answer.boxes.length+' in frame';
  await commentOnObjects(answer.boxes,()=>run===cameraRun&&!!camera,cameraController.signal);
 }catch(e){if(run===cameraRun&&e.name!=='AbortError'){$('camera-status').textContent=e.message;$('boxes').replaceChildren();$('detect').checked=false;$('commentary').checked=false;}}
 finally{cameraBusy=false;}
},1600);
$('detect').onchange=()=>{if(!$('detect').checked)$('boxes').replaceChildren();};
document.addEventListener('visibilitychange',()=>{
 if(document.hidden){cameraController?.abort();stopCamera();clearObserverFrame();}
 else void pollObserver();
});
window.addEventListener('pagehide',()=>{cameraController?.abort();stopCamera();clearObserverFrame();stopMic();});
function setVoiceStatus(text){
 $('voice-status').textContent=text;
 $('conversation-status').textContent=text;
}
function micControls(){
 const active=listening&&(conversationUntil>Date.now()||busy);
 $('talk-label').textContent=active?'End conversation':'Start conversation';
 $('mic-toggle').textContent=listening?'Turn microphone off':'Enable microphone';
 $('talk-toggle').disabled=micStarting;
 $('mic-toggle').disabled=micStarting;
 $('talk-record').disabled=micStarting||(!recording&&(spoken||busy||!!micRequest));
 $('talk-record').textContent=recording?'Send recording':'Record a question';
 $('mic-device').disabled=micStarting||recording||busy;
}
function stopMic(){
 micEpoch++;listening=false;conversationUntil=0;recording=false;micRequest?.abort();micRequest=null;
 if(mic){
  mic.stream.getTracks().forEach(track=>track.stop());
  void mic.context.close();mic=null;
 }
 $('mic-level').value=0;$('mic-input-name').textContent='Microphone is off.';
 setVoiceStatus('Microphone is off.');micControls();modules();
}
function pauseMic(paused){mic?.node.port.postMessage({paused});}
function wakeWords(text){
 return text.match(/^(?:hey[ ,]+)?(?:cassie|cassy|kassie|casey|kathy)\b[ ,.!?]*(.*)$/i);
}
function inputPreference(){
 try{return localStorage.getItem('cassie.microphone')||'';}catch{return '';}
}
async function refreshMicrophones(activeId=''){
 const menu=$('mic-device');
 const devices=await navigator.mediaDevices.enumerateDevices();
 if(!token)return;
 const choice=inputPreference(),options=[el('option','System default')];
 options[0].value='';
 for(const device of devices){
  if(device.kind!=='audioinput'||!device.deviceId||['default','communications'].includes(device.deviceId))continue;
  const option=el('option',device.label||'Microphone '+options.length);option.value=device.deviceId;options.push(option);
 }
 menu.replaceChildren(...options);
 menu.value=options.some(option=>option.value===choice)?choice:'';
 const active=options.find(option=>option.value===activeId);
 if(active&&mic)$('mic-input-name').textContent='Using '+active.textContent;
}
async function hearClip(buffer, owner, manual=false){
 if(mic!==owner||!listening||!token||spoken||busy||micRequest)return;
 if(manual){recording=false;setVoiceStatus('Transcribing your question…');}
 const request=new AbortController();micRequest=request;micControls();
 const bytes=new Uint8Array(buffer);
 let raw='';
 for(let offset=0;offset<bytes.length;offset+=8192)raw+=String.fromCharCode(...bytes.subarray(offset,offset+8192));
 try{
  const {text}=await api('speech',{pcm:btoa(raw)},AbortSignal.any([request.signal,AbortSignal.timeout(15000)]));
  if(mic!==owner||spoken||busy)return;
  if(!text){
   if(manual)setVoiceStatus('I didn’t catch any words. Check that the microphone meter moves while you speak.');
   return;
  }
  const wake=wakeWords(text);
  if(wake||manual||conversationUntil>Date.now()){
   setPage('command');
   $('talk-toggle').focus({preventScroll:true});
   if(wake&&!wake[1]){
    const acknowledgement='I’m here, Titan.';
    message(acknowledgement);
    await speak(acknowledgement);
    if(mic===owner){
     conversationUntil=Date.now()+CONVERSATION_MS;
     setVoiceStatus('Listening for your question.');
    }
   }else{
    await send(wake?wake[1]:text,true);
   }
  }
 }catch(error){
  if(mic===owner&&!request.signal.aborted)setVoiceStatus(error.message);
 }finally{if(micRequest===request)micRequest=null;micControls();}
}
async function startMic(conversation=false){
 if(demo){toast('Voice is simulated in this offline preview.');return false;}
 if(!token||micStarting)return false;
 if(mic){
  if(conversation){conversationUntil=Date.now()+CONVERSATION_MS;setVoiceStatus('I’m listening. Go ahead.');micControls();}
  return true;
 }
 const epoch=++micEpoch;
 let context,stream;
 micStarting=true;micControls();setVoiceStatus('Opening the microphone…');
 try{
  if(!navigator.mediaDevices?.getUserMedia)throw new Error('Microphone input is unavailable in this console.');
  context=new AudioContext();
  await context.resume();
  const input=inputPreference();
  const constraints={channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true};
  try{
   stream=await navigator.mediaDevices.getUserMedia({audio:input?{...constraints,deviceId:{exact:input}}:constraints});
  }catch(error){
   if(!input||!['NotFoundError','OverconstrainedError'].includes(error.name))throw error;
   stream=await navigator.mediaDevices.getUserMedia({audio:constraints});
  }
  if(!(await api('speech',undefined,AbortSignal.timeout(5000))).available)throw new Error('Install the desktop voice update to enable local speech.');
  await context.audioWorklet.addModule('/mic-worklet.js');
  if(!token||epoch!==micEpoch)return false;
  const node=new AudioWorkletNode(context,'cassie-mic',{channelCount:1,channelCountMode:'explicit'});
  const silence=context.createGain();silence.gain.value=0;
  const source=context.createMediaStreamSource(stream);
  source.connect(node).connect(silence).connect(context.destination);
  const owner={context,stream,node,source};
  node.port.onmessage=event=>{
   if(mic!==owner)return;
   if(event.data.clip)void hearClip(event.data.clip,owner,event.data.manual);
   else if(event.data.empty)setVoiceStatus('That recording was empty. Try again and watch the microphone meter.');
   else if(typeof event.data.level==='number')$('mic-level').value=Math.min(1,Math.sqrt(event.data.level*5));
  };
  const track=stream.getAudioTracks()[0];
  track.onended=()=>{if(mic===owner){stopMic();setVoiceStatus('Microphone disconnected.');}};
  mic=owner;listening=true;
  if(conversation)conversationUntil=Date.now()+CONVERSATION_MS;
  $('mic-input-name').textContent='Using '+(track.label||'system microphone');
  void refreshMicrophones(track.getSettings().deviceId).catch(()=>{});
  setVoiceStatus(conversation?'I’m listening. Go ahead.':'Say “CASSIE” to talk.');
  modules();
  return true;
 }catch(error){
  if(epoch===micEpoch)setVoiceStatus(error.name==='NotAllowedError'?'Microphone permission is blocked. Allow it in Chromium, then try again.':error.message);
  return false;
 }finally{
  if(mic?.context!==context){
   stream?.getTracks().forEach(track=>track.stop());
   if(context&&context.state!=='closed')void context.close();
  }
  micStarting=false;micControls();
 }
}
$('mic-toggle').onclick=()=>{if(mic)stopMic();else void startMic();};
$('talk-toggle').onclick=()=>{
 if(listening&&(conversationUntil>Date.now()||busy))stopMic();else void startMic(true);
};
$('talk-record').onclick=async()=>{
 if(recording){
  recording=false;mic?.node.port.postMessage({record:false});
  setVoiceStatus('Sending your recording…');micControls();return;
 }
 if(!await startMic()||spoken||busy||micRequest)return;
 recording=true;mic.node.port.postMessage({record:true});
 setVoiceStatus('Recording. Select Send recording when you finish.');micControls();
};
$('mic-device').onchange=async event=>{
 const input=event.target.value;
 try{localStorage.setItem('cassie.microphone',input);}catch{}
 if(mic){
  const active=conversationUntil>Date.now();
  stopMic();await startMic(active);
 }
};
navigator.mediaDevices?.addEventListener?.('devicechange',()=>{if(token)void refreshMicrophones().catch(()=>{});});
setInterval(()=>{
 if(listening&&conversationUntil&&conversationUntil<=Date.now()&&!busy&&!spoken&&!micRequest&&!recording){
  conversationUntil=0;micControls();setVoiceStatus('Say “CASSIE” to resume.');
 }
},1000);
$('camera-look').onclick=()=>{
 setPage('command');void send('What do you see right now?',listening,true);
};
$('test-voice').onclick=()=>speak('CASSIE online. I do enjoy a dramatic entrance.');
$('review-form').onsubmit=async e=>{
 e.preventDefault();const requirement=$('review').value.trim();if(!requirement)return;
 $('review-submit').disabled=true;$('review-result').textContent='Drafting…';
 try{$('review-result').textContent=demo?'Example proposal · no files changed\n\nGoal: '+requirement+'\n\n1. Keep the change scoped to the selected file.\n2. Show the diff and explain the behavior it changes.\n3. Test the revised path before releasing it.':(await api('proposal',{target:$('review-target').value,request:requirement})).content;}
 catch(error){$('review-result').textContent=error.message;}finally{$('review-submit').disabled=false;}
};
$('copy').onclick=async()=>{try{await navigator.clipboard.writeText($('diagnostic').textContent);toast('Commands copied.');}catch{toast('Select the commands and copy them manually.');}};
$('browser-form').onsubmit=e=>{e.preventDefault();try{const u=new URL($('browser-url').value);if(u.protocol!=='https:'||u.username||u.password)throw new Error();window.open(u.href,'_blank','noopener,noreferrer');}catch{toast('Enter an HTTPS address without credentials.');}};
async function loadInbox(){
 const box=$('inbox');box.replaceChildren();
 if(demo){box.append(el('p','In the preview, no files are present or changed.'));return;}
 if(!token)return;
 try{
  const result=await api('inbox');if(!token||page!=='workshop')return;
  if(!result.files.length)box.append(el('p','The staging inbox is empty or not enabled.'));
  for(const name of result.files){
   const row=el('div','','network-item');row.append(el('strong',name));const b=el('button','Isolate file','quiet');
   b.onclick=async()=>{if(!confirm('Move this inbox file into quarantine?'))return;
    try{const r=await api('quarantine',{name});toast('Isolated as '+r.isolated);await loadInbox();}catch(e){toast(e.message);}
   };row.append(b);box.append(row);
  }
 }catch(e){if(token)toast(e.message);}
}
async function enter(){
 const session=await api('session'),data=await api('catalog');
 if(!token)return;
 catalog=data.entries;catalogInfo=data.catalog||null;notes=session.notes||[];$('tone').value=session.profile?.tone||'adaptive';$('style').value=session.profile?.style||'';$('chat-log').replaceChildren();
 for(const row of session.chat||[])message(row.content,row.role,row.sources);
 if(!$('chat-log').children.length)message('I’m here. What are we getting into?');
 $('unlock').close();$('lock').hidden=false;void refreshMicrophones().catch(()=>{});await pollObserver();await refresh();
}
$('unlock').addEventListener('cancel',e=>e.preventDefault());
$('unlock-form').onsubmit=async e=>{e.preventDefault();token=$('key').value.trim();$('login-error').textContent='';
 try{await enter();$('key').value='';}catch(error){token='';$('login-error').textContent=error.message;}
};
$('lock').onclick=()=>{token='';live=null;notes=[];catalog=[];catalogInfo=null;expression='nominal';spoken=false;
 if($('clear-dialog').open)$('clear-dialog').close();
 chatAbort?.abort();chatAbort=null;busy=false;$('send').disabled=false;
 if(audio){audio.pause();audio.dispatchEvent(new Event('ended'));}
 cameraController?.abort();stopCamera();alwaysEpoch++;showObserver({enabled:false,detail:''});stopMic();$('chat-log').replaceChildren();$('datasets').replaceChildren();$('graph').replaceChildren();$('topic').replaceChildren();$('network-list').replaceChildren();$('inbox').replaceChildren();$('review-result').textContent='';
 $('message').value='';$('note').value='';$('review').value='';$('style').value='';$('tone').value='adaptive';$('lock').hidden=true;status();modules();network();setPage('command');$('unlock').showModal();};
$('profile-form').onsubmit=async e=>{e.preventDefault();
 if(demo){toast('Personality preferences can be saved in the installed console.');return;}
 try{await api('profile',{tone:$('tone').value,style:$('style').value});toast('Personality preferences saved.');}catch(error){toast(error.message);}
};
function openClearDialog(){
 if((!demo&&!token)||clearing||$('clear-dialog').open)return;
 $('clear-error').textContent='';
 $('clear-dialog').showModal();
}
$('clear').onclick=$('clear-command').onclick=openClearDialog;
$('clear-cancel').onclick=()=>$('clear-dialog').close();
$('clear-dialog').addEventListener('cancel',event=>{if(clearing)event.preventDefault();});
$('clear-form').onsubmit=async event=>{
 event.preventDefault();
 if(clearing||(!demo&&!token))return;
 if(busy){$('clear-error').textContent='CASSIE is answering. Wait for the reply to finish, then try again.';return;}
 const session=token;
 clearing=true;$('clear-confirm').disabled=true;$('clear-cancel').disabled=true;
 $('clear-error').textContent='';
 try{
  if(!demo)await api('chat/clear',{},AbortSignal.timeout(8000));
  if(session!==token)return;
  $('chat-log').replaceChildren();$('message').value='';
  message('Fresh start. What are we getting into?');
  $('clear-dialog').close();toast('Conversation cleared.');
 }catch(error){if(session===token)$('clear-error').textContent=error.message;}
 finally{clearing=false;$('clear-confirm').disabled=false;$('clear-cancel').disabled=false;}
};
$('export').onclick=async()=>{if(demo){toast('The preview contains sample data only.');return;}
 try{const result=await api('export'),a=el('a');a.download='CASSIE-export.json';
   a.href=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);
 }catch(error){toast(error.message);}
};
function clock(){$('clock').textContent=new Intl.DateTimeFormat(undefined,{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'UTC'}).format(new Date())+' UTC';}
clock();setInterval(clock,15000);status();
if(demo){
 $('mode').lastChild.textContent=' PREVIEW · SIMULATED';$('rail-status').textContent='DESIGN PREVIEW';$('scenarios').hidden=false;
 catalog=demo.entries;notes=demo.notes;message('Hey, Titan. I’m online. The dramatic lighting is entirely necessary.');refresh();
}else{
 $('live-strip').hidden=false;$('unlock').showModal();setInterval(()=>{if(!document.hidden)refresh();},30000);
}
