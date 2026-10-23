const { test, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const readline = require('node:readline');
const root = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'router-replay-'));
fs.mkdirSync(path.join(root, 'bin'));
after(() => fs.rmSync(root, { recursive: true, force: true }));
const router = path.resolve(__dirname, '../alans-way/scripts/workspace-router.cjs');
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function until(read, label) {
  const end = Date.now() + 6000;
  while (!read()) { assert.ok(Date.now() < end, label); await sleep(10); }
  return read();
}
// Redirect only the router's private SSH-dir filesystem operations into scratch.
// The executable called ssh below is a local fixture, never an SSH client.
fs.writeFileSync(path.join(root, 'sandbox.cjs'), `
const fs=require('node:fs'),path=require('node:path');
const redirect=p=>p==='/tmp/wsr-'+process.getuid()?path.join(process.env.ROUTER_TEST_DIR,'ssh-dir'):p;
for(const name of ['mkdirSync','lstatSync']){const original=fs[name];fs[name]=(p,...args)=>original(redirect(p),...args);}
const now=Date.now;
Date.now=()=>now()+Number(fs.existsSync(path.join(process.env.ROUTER_TEST_DIR,'clock'))?fs.readFileSync(path.join(process.env.ROUTER_TEST_DIR,'clock'),'utf8'):0);
if(process.env.ROUTER_TEST_BROKEN_PIPE){
 const cp=require('node:child_process'),spawn=cp.spawn;
 cp.spawn=(...args)=>{const child=spawn(...args);if(args[0]==='ssh')Object.defineProperty(child.stdin,'writable',{get(){
  if(fs.existsSync(path.join(process.env.ROUTER_TEST_DIR,'block-mac-pipe'))){fs.writeFileSync(path.join(process.env.ROUTER_TEST_DIR,'pipe-blocked'),'');return false;}
  return !this.destroyed&&!this.writableEnded;
 }});return child;};
}
const read=fs.readFileSync;
fs.readFileSync=(file,...args)=>process.env.ROUTER_TEST_HOLD&&file===path.join(process.env.ROUTER_TEST_DIR,'absent-connection.json')?JSON.stringify({url:'http://127.0.0.1:1',token:'fixture-only'}):read(file,...args);
global.fetch=async()=>{
 if(!process.env.ROUTER_TEST_HOLD)throw new Error('Fixture forbids network access');
 fs.writeFileSync(path.join(process.env.ROUTER_TEST_DIR,'restore-started'),'');
 await new Promise(r=>setTimeout(r,400));return {status:404};
};
`);
fs.writeFileSync(path.join(root, 'backend.cjs'), `
const fs=require('node:fs'),path=require('node:path');
const file=path.join(process.env.ROUTER_TEST_DIR,'backend.jsonl');
const host=process.argv[2]==='fake-mac'?'mac':'vm';
const past=fs.existsSync(file)?fs.readFileSync(file,'utf8').trim().split('\\n').filter(Boolean).map(JSON.parse):[];
const ordinal=past.filter(e=>e.kind==='start'&&e.host===host).length+1;
const log=(kind,extra={})=>fs.appendFileSync(file,JSON.stringify({at:Date.now(),kind,host,ordinal,pid:process.pid,...extra})+'\\n');
log('start');
if(host==='mac'&&ordinal>1&&process.env.ROUTER_TEST_RECONNECT==='exit'){process.exitCode=255;return;}
require('node:readline').createInterface({input:process.stdin}).on('line',line=>{
 const m=JSON.parse(line);log('receive',{m});
 if(host==='mac'&&ordinal>1&&process.env.ROUTER_TEST_RECONNECT==='silent')return;
 if(m.method==='notifications/cancelled'){
  if(process.env.ROUTER_TEST_IGNORE_CANCEL)return;
  process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:m.params.requestId,result:{isError:true,content:[{type:'text',text:JSON.stringify({cancelled:true,completed:[0]})}]}})+'\\n');return;
 }
 if(m.id===undefined||m.params?.hang)return;
 if(m.method==='tools/call')log('effect',{id:m.id,name:m.params.name,args:m.params.arguments});
 if(m.method==='tools/call'&&m.params.arguments?.die&&(!m.params.arguments.firstMacOnly||(host==='mac'&&ordinal===1))){setTimeout(()=>process.exit(m.params.arguments.dieCode||0),20);return;}
 if(host==='mac'&&ordinal===1&&m.params?.arguments?.hangFirstMac)return;
 if(m.method==='tools/call'&&(m.params.arguments?.hang||(m.params.arguments?.hangVm&&host==='vm')))return;
 if(host==='mac'&&ordinal===1&&process.env.ROUTER_TEST_MODE!=='normal'){
   if(process.env.ROUTER_TEST_MODE==='established'&&m.method==='initialize'){}
   else {if(process.env.ROUTER_TEST_MODE!=='retry'&&m.method==='tools/call')setTimeout(()=>process.exit(0),Number(process.env.ROUTER_TEST_EXIT_MS)||20);return;}
 }
 const result=m.method==='initialize'?{protocolVersion:'2024-11-05',capabilities:{tools:{}},serverInfo:{name:'owned-fake',version:'1'}}
 :{content:[{type:'text',text:JSON.stringify(m.params?.name==='cua_alans_way_snapshot'?{url:'https://example.invalid/ordinary',tab:{id:'fixture-tab',epoch:1},elements:[{ref:'e1',role:'button',name:'Read guide'}],truncated:{text:false,elements:false},iframes:[]}:{ok:true,host:host==='mac'?'local':'vps',dispatched:true})}]};
 process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:m.id,result})+'\\n');
});
`);
fs.writeFileSync(path.join(root, 'bin/ssh'), '#!/bin/sh\nexec "$ROUTER_TEST_NODE" "$ROUTER_TEST_BACKEND" fake-mac\n', { mode: 0o755 });
function client(t, mode, env = {}) {
  const dir = fs.mkdtempSync(path.join(root, 'case-'));
  fs.mkdirSync(path.join(dir,'bin'));
  fs.copyFileSync(path.join(root,'bin/ssh'),path.join(dir,'bin/ssh'));
  const state = path.join(dir, 'state.json');
  fs.writeFileSync(state, JSON.stringify({state:env.ROUTER_TEST_HOLD?'offline':'online',since:new Date().toISOString(),lastSeenOnline:new Date().toISOString()}));
  fs.writeFileSync(path.join(dir,'router-last-self-probe'),String(Date.now()));
  const p = spawn(process.execPath, ['--require',path.join(root,'sandbox.cjs'),router,
    '--bot-id','fixture-client','--mac-ssh','owned-fake-only','--mac-script','/owned/fake.cjs',
    '--mac-state-file',state,'--vps-script',path.join(root,'backend.cjs'),'--vps-connection',path.join(dir,'absent-connection.json')],
    {env:{PATH:path.join(dir,'bin'),HERMES_HOME:path.join(dir,'profile'),ROUTER_TEST_NODE:process.execPath,ROUTER_TEST_BACKEND:path.join(root,'backend.cjs'),ROUTER_TEST_MODE:mode,ROUTER_TEST_DIR:dir,
      HERMES_ROUTER_MAC_WATCHDOG_MS:'500',HERMES_ROUTER_MAC_RETRY_MS:'500',...env},stdio:['pipe','pipe','pipe']});
  const messages=[]; let stderr='',closed=false;
  p.stdin.on('error',()=>{});
  p.stderr.on('data',b=>stderr+=b);
  readline.createInterface({input:p.stdout}).on('line',line=>messages.push(JSON.parse(line)));
  p.on('close',()=>closed=true);
  const events=()=>fs.existsSync(path.join(dir,'backend.jsonl'))?fs.readFileSync(path.join(dir,'backend.jsonl'),'utf8').trim().split('\n').filter(Boolean).map(JSON.parse):[];
  t.after(async()=>{
    p.stdin.end();
    try { await until(()=>closed,'router cleanup'); }
    finally {
      if(!closed)p.kill('SIGKILL');
      for(const e of events().filter(e=>e.kind==='start')) {
        let alive=false;try{process.kill(e.pid,0);alive=true;}catch{}
        if(alive){process.kill(e.pid,'SIGKILL');assert.fail('router left an owned backend alive');}
      }
      fs.writeFileSync(path.join(dir,'client.json'),JSON.stringify({messages,stderr},null,2));
    }
  });
  const send=m=>p.stdin.write(JSON.stringify({jsonrpc:'2.0',...m})+'\n');
  const init=()=>send({id:1,method:'initialize',params:{protocolVersion:'2024-11-05',capabilities:{elicitation:{}},clientInfo:{name:'fixture-client',version:'1'}}});
  const call=(id,name,args)=>send({id,method:'tools/call',params:{name,arguments:args}});
  const recv=id=>until(()=>messages.find(m=>m.id===id),'reply '+id+': '+stderr);
  const effects=id=>events().filter(e=>e.kind==='effect'&&e.id===id);
  return {send,init,call,recv,effects,events,messages,dir,stderr:()=>stderr};
}
const writes = [
  ['navigate', 'cua_alans_way_action', {tabId:'fixture-tab',action:'navigate',url:'https://example.invalid/ordinary'}],
  ['open', 'cua_alans_way_open', {url:'https://example.invalid/ordinary'}],
  ['click', 'cua_alans_way_action', {tabId:'fixture-tab',host:'computer',action:'click',name:'Read guide'}],
  ['type', 'cua_alans_way_action', {tabId:'fixture-tab',action:'type',name:'Search',text:'guide'}],
];
for (const mode of ['retry', 'exit']) for (const [action, name, args] of writes) {
  test('pre-ready '+action+' runs once on '+mode, async t => {
    const c=client(t,mode);
    if(action==='click'){c.call(10,'cua_alans_way_snapshot',{host:'vm',tabId:'fixture-tab'});await c.recv(10);}
    c.init(); c.call(2,name,args);
    const reply=await c.recv(2);
    await c.recv(1); await sleep(100);
    assert.equal(c.effects(2).length,1);
    assert.equal(reply.result.isError,true);
    assert.match(JSON.stringify(reply),/may or may not have happened.*not retried/i);
    assert.equal(c.messages.filter(m=>m.id===2).length,1);
    assert.match(c.stderr(),mode==='retry'?/retrying the spawn/:/died before its first response/);
  });
}
for (const mode of ['retry','exit']) test('pre-ready reads replay on '+mode,async t=>{
  const c=client(t,mode);c.init();c.call(2,'cua_alans_way_status',{});
  await c.recv(2);
  assert.deepEqual(c.effects(2).map(e=>e.host),mode==='retry'?['mac','mac']:['mac','vm']);
  const logs=c.stderr().split('\n').filter(line=>line.startsWith('workspace-router: served ')).map(line=>JSON.parse(line.slice('workspace-router: served '.length)));
  assert.equal(logs.length,1,'only the completed read is logged, never its replay attempts');
  assert.equal(logs[0].host,mode==='retry'?'mac':'vm');
  assert.equal(logs[0].selection,mode==='retry'?'defaulted':'fallback');
  assert.equal(logs[0].reason,mode==='retry'?null:'backend_unavailable');
});
test('established reconnect refuses uncertain write and replays read only',async t=>{
  const c=client(t,'established'); c.init(); await c.recv(1);
  c.call(2,'cua_alans_way_action',{tabId:'owned-tab',action:'navigate',url:'https://example.invalid/ordinary'});
  c.call(3,'cua_alans_way_status',{});
  const reply=await c.recv(2); await c.recv(3);
  assert.equal(reply.result.isError,true);
  assert.match(JSON.stringify(reply),/NOT retried|not retried/);
  assert.equal(c.effects(2).length,1);
  assert.deepEqual(c.effects(3).map(e=>e.host),['mac','mac']);
});
test('a dropped Mac link reinitializes on Mac and preserves its tab and epoch',async t=>{
  const c=client(t,'normal');c.init();await c.recv(1);
  c.send({method:'notifications/initialized'});
  c.call(2,'cua_alans_way_snapshot',{tabId:'fixture-tab'});await c.recv(2);
  c.call(3,'cua_alans_way_action',{action:'navigate',url:'https://example.invalid/ordinary',hang:true});
  c.call(4,'cua_alans_way_snapshot',{hangFirstMac:true});
  await until(()=>c.effects(3).length===1&&c.effects(4).length===1,'pending Mac calls');
  c.call(5,'cua_alans_way_status',{die:true,dieCode:255,firstMacOnly:true});
  const lost=await c.recv(3),read=await c.recv(4);await c.recv(5);
  assert.equal(lost.result.isError,true);assert.match(JSON.stringify(lost),/may or may not have happened.*not retried/i);
  assert.equal(c.effects(3).length,1);
  assert.equal(read.result._meta.workspace.host,'mac');
  assert.deepEqual(c.effects(4).map(e=>e.host),['mac','mac']);
  assert.deepEqual(c.effects(4).map(e=>[e.args.tabId,e.args.epoch]),[['fixture-tab',1],['fixture-tab',1]]);
  const inits=c.events().filter(e=>e.kind==='receive'&&e.m.method==='initialize');
  assert.equal(inits.length,2);assert.deepEqual(inits[1].m.params,inits[0].m.params);
  const replay=c.events().filter(e=>e.kind==='receive'&&e.host==='mac'&&e.ordinal===2);
  assert.deepEqual(replay.slice(0,2).map(e=>e.m.method),['initialize','notifications/initialized']);
  assert.equal(c.events().filter(e=>e.kind==='start'&&e.host==='vm').length,0);
  assert.match(c.stderr(),/Mac backend exited \(255\) — reconnecting to Mac/);
  await sleep(650);
  c.call(6,'cua_alans_way_snapshot',{});assert.equal((await c.recv(6)).result._meta.workspace.host,'mac');
  assert.deepEqual(c.effects(6).map(e=>[e.args.tabId,e.args.epoch]),[['fixture-tab',1]]);
  for(const id of [1,3,4,5,6])assert.equal(c.messages.filter(m=>m.id===id).length,1);
  const rows=c.stderr().split('\n').filter(l=>l.startsWith('workspace-router: served ')).map(l=>JSON.parse(l.slice('workspace-router: served '.length)));
  assert.ok(rows.every(r=>r.host==='mac'));
  assert.deepEqual(Object.keys(rows.find(r=>r.requestId===4)).sort(),['elapsedMs','host','reason','requestId','selection','tool']);
});
for(const failure of ['exit','silent','missing'])test('a Mac reconnect that is '+failure+' fails over once',async t=>{
  const c=client(t,'normal',{ROUTER_TEST_RECONNECT:failure});c.init();await c.recv(1);
  c.call(2,'cua_alans_way_status',{hangFirstMac:true});
  await until(()=>c.effects(2).length===1,'pending read');
  if(failure==='missing')fs.unlinkSync(path.join(c.dir,'bin/ssh'));
  c.call(3,'cua_alans_way_open',{url:'https://example.invalid/ordinary',die:true,dieCode:255});
  assert.match(JSON.stringify(await c.recv(3)),/may or may not have happened.*not retried/i);
  assert.equal((await c.recv(2)).result._meta.workspace.host,'vps');
  assert.equal(c.effects(3).length,1);
  assert.deepEqual(c.events().filter(e=>e.kind==='start').map(e=>e.host),failure==='missing'?['mac','vm']:['mac','mac','vm']);
  assert.equal(c.stderr().split('reconnecting to Mac').length-1,1);
  assert.match(c.stderr(),failure==='silent'?/backend silent 500ms/:failure==='missing'?/failed to spawn backend.*ENOENT/:/died before its first response/);
});
for(const state of ['offline','stale'])test('a dropped link with '+state+' mac-watch state fails over directly',async t=>{
  const c=client(t,'normal');c.init();await c.recv(1);
  const file=path.join(c.dir,'state.json');
  fs.writeFileSync(file,JSON.stringify({state:state==='offline'?'offline':'online',since:new Date().toISOString()}));
  if(state==='stale'){const old=new Date(Date.now()-60000);fs.utimesSync(file,old,old);}
  c.call(2,'cua_alans_way_status',{die:true,firstMacOnly:true,dieCode:255});
  assert.equal((await c.recv(2)).result._meta.workspace.host,'vps');
  assert.deepEqual(c.events().filter(e=>e.kind==='start').map(e=>e.host),['mac','vm']);
  assert.ok(!c.stderr().includes('reconnecting'));
});
test('a flapping Mac link gets no second reconnect within a minute',async t=>{
  const c=client(t,'normal');c.init();await c.recv(1);
  c.call(2,'cua_alans_way_status',{die:true,firstMacOnly:true,dieCode:255});
  assert.equal((await c.recv(2)).result._meta.workspace.host,'mac');
  c.call(3,'cua_alans_way_status',{hang:true});await until(()=>c.effects(3).length===1,'pending read');
  process.kill(c.events().find(e=>e.kind==='start'&&e.host==='mac'&&e.ordinal===2).pid,'SIGTERM');
  await until(()=>c.events().some(e=>e.kind==='start'&&e.host==='vm'),'VM failover');
  c.send({method:'notifications/cancelled',params:{requestId:3}});await c.recv(3);
  c.call(4,'cua_alans_way_status',{});assert.equal((await c.recv(4)).result._meta.workspace.host,'vps');
  assert.deepEqual(c.events().filter(e=>e.kind==='start').map(e=>e.host),['mac','mac','vm']);
  assert.equal(c.stderr().split('reconnecting to Mac').length-1,1);
});
test('a later drop may reconnect again after a minute, even with no pending calls',async t=>{
  const c=client(t,'normal');c.init();await c.recv(1);
  c.call(2,'cua_alans_way_status',{die:true,firstMacOnly:true});await c.recv(2);
  fs.writeFileSync(path.join(c.dir,'clock'),'60001');
  const future=new Date(Date.now()+60001);fs.utimesSync(path.join(c.dir,'state.json'),future,future);
  process.kill(c.events().find(e=>e.kind==='start'&&e.host==='mac'&&e.ordinal===2).pid,'SIGTERM');
  await until(()=>c.events().some(e=>e.kind==='receive'&&e.ordinal===3&&e.m.method==='initialize'),'idle handshake replay');
  await sleep(650);
  c.call(3,'cua_alans_way_status',{});assert.equal((await c.recv(3)).result._meta.workspace.host,'mac');
  assert.deepEqual(c.events().filter(e=>e.kind==='start').map(e=>e.host),['mac','mac','mac']);
  assert.equal(c.stderr().split('reconnecting to Mac').length-1,2);
});
test('a write never handed to the broken Mac pipe runs once after reconnect',async t=>{
  const c=client(t,'normal',{ROUTER_TEST_BROKEN_PIPE:'1'});c.init();await c.recv(1);
  const block=path.join(c.dir,'block-mac-pipe');fs.writeFileSync(block,'');
  c.call(2,'cua_alans_way_open',{url:'https://example.invalid/ordinary'});
  await until(()=>fs.existsSync(path.join(c.dir,'pipe-blocked')),'unwritable Mac pipe');
  assert.equal(c.effects(2).length,0);fs.unlinkSync(block);
  process.kill(c.events().find(e=>e.kind==='start'&&e.host==='mac').pid,'SIGTERM');
  assert.equal((await c.recv(2)).result._meta.workspace.host,'mac');
  assert.deepEqual(c.effects(2).map(e=>[e.host,e.ordinal]),[['mac',2]]);
});
test('failover refuses pending and later Mac tab calls even with an explicit VM host',async t=>{
  const c=client(t,'normal',{ROUTER_TEST_RECONNECT:'exit'});c.init();await c.recv(1);
  c.call(2,'cua_alans_way_snapshot',{tabId:'fixture-tab'});await c.recv(2);
  c.call(3,'cua_alans_way_snapshot',{hangFirstMac:true});
  await until(()=>c.effects(3).length===1,'pending Mac tab read');
  c.call(4,'cua_alans_way_status',{die:true,firstMacOnly:true});await c.recv(4);
  const lost=await c.recv(3);assert.equal(lost.result.isError,true);
  assert.match(JSON.stringify(lost),/Mac connection dropped.*tab.*Mac/i);
  for(const [id,args] of [[5,{tabId:'fixture-tab'}],[6,{tabId:'fixture-tab',host:'vm'}],[7,{}],[8,{action:'batch',steps:[{tabId:'fixture-tab',action:'navigate',url:'https://example.invalid/ordinary'}]}]]){
    c.call(id,id===8?'cua_alans_way_action':'cua_alans_way_snapshot',args);
    const reply=await c.recv(id);assert.equal(reply.result.isError,true);
    assert.match(JSON.stringify(reply),/Mac connection dropped.*tab.*Mac/i);
    assert.equal(c.effects(id).length,0);
  }
  assert.deepEqual(c.effects(3).map(e=>e.host),['mac']);
  c.call(9,'cua_alans_way_snapshot',{tabId:'new-vm-tab',host:'vm'});
  assert.equal((await c.recv(9)).result._meta.workspace.host,'vps');
  assert.deepEqual(c.effects(9).map(e=>e.host),['vm']);
});
test('a pending Mac tab read without an earlier tab reply cannot replay on the VM',async t=>{
  const c=client(t,'normal',{ROUTER_TEST_RECONNECT:'exit'});c.init();await c.recv(1);
  c.call(2,'cua_alans_way_snapshot',{tabId:'unobserved-mac-tab',hangFirstMac:true});
  await until(()=>c.effects(2).length===1,'pending unobserved Mac tab');
  c.call(3,'cua_alans_way_status',{die:true,firstMacOnly:true});await c.recv(3);
  assert.match(JSON.stringify(await c.recv(2)),/Mac connection dropped.*tab.*Mac/i);
  assert.deepEqual(c.effects(2).map(e=>e.host),['mac']);
  c.call(4,'cua_alans_way_snapshot',{tabId:'unobserved-mac-tab',host:'vm'});
  assert.match(JSON.stringify(await c.recv(4)),/Mac connection dropped.*tab.*Mac/i);
  assert.equal(c.effects(4).length,0);
});
test('an uncertain action retains Mac tab affinity if its reconnect later fails',async t=>{
  const c=client(t,'normal',{ROUTER_TEST_RECONNECT:'exit'});c.init();await c.recv(1);
  c.call(2,'cua_alans_way_action',{tabId:'unobserved-action-tab',action:'navigate',url:'https://example.invalid/ordinary',hang:true});
  await until(()=>c.effects(2).length===1,'pending Mac action');
  c.call(3,'cua_alans_way_status',{die:true,firstMacOnly:true});
  assert.match(JSON.stringify(await c.recv(2)),/may or may not have happened.*not retried/i);
  assert.equal((await c.recv(3)).result._meta.workspace.host,'vps');
  c.call(4,'cua_alans_way_snapshot',{tabId:'unobserved-action-tab',host:'vm'});
  assert.match(JSON.stringify(await c.recv(4)),/Mac connection dropped.*tab.*Mac/i);
  assert.equal(c.effects(2).length,1);assert.equal(c.effects(4).length,0);
});
test('Donate refuses before dispatch and is absent from startup replay',async t=>{
  const c=client(t,'exit'); c.init();
  c.call(2,'cua_alans_way_action',{tabId:'owned-tab',action:'click',name:'Donate'});
  assert.match(JSON.stringify(await c.recv(2)),/commit_required/);
  c.call(3,'cua_alans_way_action',{tabId:'owned-tab',action:'click',name:'Donate',commit:{kind:'purchase',summary:'Owned fake donation'}});
  assert.match(JSON.stringify(await c.recv(3)),/approval_binding_unavailable/);
  c.call(4,'cua_alans_way_open',{url:'https://example.invalid/ordinary'}); await c.recv(4);
  assert.equal(c.effects(2).length,0);assert.equal(c.effects(3).length,0);
});
test('approved pre-ready commit is unbuffered and never replayed',async t=>{
  const c=client(t,'retry'); c.init();
  c.call(2,'cua_alans_way_open',{url:'https://example.invalid/submit',commit:{kind:'submit',summary:'Owned fake submission'}});
  const approval=await until(()=>c.messages.find(m=>m.method==='elicitation/create'),'approval prompt');
  c.send({id:approval.id,result:{action:'accept',content:{approve:true}}});
  await until(()=>c.effects(2).length===1,'approved dispatch');
  await c.recv(1);
  const reply=await c.recv(2);assert.equal(reply.result.isError,true);assert.match(JSON.stringify(reply),/may or may not have happened.*not retried/i);
  await sleep(100);assert.equal(c.effects(2).length,1);
  assert.match(c.stderr(),/retrying the spawn/);
});

for (const host of ['computer','vm']) test(host+' dispatch budgets preserve other metadata and use the batch cap',async t=>{
  const c=client(t,'normal',{HERMES_ROUTER_CALL_HARD_MS:'10000',HERMES_ROUTER_BATCH_HARD_MS:'12000'});c.init();await c.recv(1);
  for(const [id,name,args,cap] of [
    [2,'cua_alans_way_status',{host},7000],
    [3,'cua_alans_way_action',{host,action:'batch',steps:[{action:'type',text:'guide'}]},9000],
  ]) {
    c.send({id,method:'tools/call',params:{name,arguments:args,_meta:{'fixture/keep':'value','alans-way/remainingMs':999999}}});await c.recv(id);
    const meta=c.events().find(e=>e.kind==='receive'&&e.m.id===id).m.params._meta;
    assert.equal(meta['fixture/keep'],'value');
    assert.ok(Number.isInteger(meta['alans-way/remainingMs']));
    assert.ok(meta['alans-way/remainingMs']<=cap&&meta['alans-way/remainingMs']>cap-1000,JSON.stringify(meta));
  }
});
for(const mode of ['retry','exit']) test('read budget decreases across '+mode,async t=>{
  const c=client(t,mode);c.init();c.call(2,'cua_alans_way_status',{});await c.recv(2);
  const frames=c.events().filter(e=>e.kind==='receive'&&e.m.id===2);
  assert.equal(frames.length,2);
  const budgets=frames.map(e=>e.m.params._meta?.['alans-way/remainingMs']);
  assert.ok(Number.isInteger(budgets[0]),JSON.stringify(budgets));
  assert.ok(budgets[1]<budgets[0],JSON.stringify(budgets));
  assert.ok(Math.abs((budgets[0]-budgets[1])-(frames[1].at-frames[0].at))<100);
});
test('expired read is answered without dispatching on watchdog retry',async t=>{
  const c=client(t,'retry',{HERMES_ROUTER_CALL_HARD_MS:'3300'});c.init();c.call(2,'cua_alans_way_status',{});
  const reply=await c.recv(2);await c.recv(1);
  assert.equal(reply.result.isError,true);assert.match(JSON.stringify(reply),/in time/);
  assert.equal(c.effects(2).length,1);
});
test('approval wait consumes the accepted call budget',async t=>{
  const c=client(t,'normal');c.init();await c.recv(1);
  c.call(2,'cua_alans_way_open',{url:'https://example.invalid/submit',commit:{kind:'submit',summary:'Fixture submission'}});
  const approval=await until(()=>c.messages.find(m=>m.method==='elicitation/create'),'approval prompt');await sleep(150);
  c.send({id:approval.id,result:{action:'accept',content:{approve:true}}});await c.recv(2);
  const budget=c.events().find(e=>e.kind==='receive'&&e.m.id===2).m.params._meta?.['alans-way/remainingMs'];
  assert.ok(Number.isInteger(budget)&&budget<=76850,JSON.stringify(budget));
  assert.equal(c.effects(2).length,1);
});

for(const host of ['computer','vm']) test('cancellation reaches only the '+host+' request owner',async t=>{
  const c=client(t,'normal');c.init();await c.recv(1);
  const id='cancel-'+host+'🌿';c.call(id,'cua_alans_way_status',{host,hang:true});
  await until(()=>c.effects(id).length===1,'call dispatched');
  c.send({method:'notifications/cancelled',params:{requestId:id,reason:'Fixture stopped'}});
  const reply=await c.recv(id);assert.deepEqual(JSON.parse(reply.result.content[0].text).completed,[0]);
  const cancels=c.events().filter(e=>e.m?.method==='notifications/cancelled');
  assert.equal(cancels.length,1);assert.equal(cancels[0].host,host==='computer'?'mac':'vm');
  assert.deepEqual(cancels[0].m.params,{requestId:id,reason:'Fixture stopped'});
});
for(const macFinished of [false,true]) test('merged tabs cancellation translates both IDs, computer finished='+macFinished,async t=>{
  const c=client(t,'normal');c.init();await c.recv(1);
  c.call(2,'cua_alans_way_status',{host:'vm'});await c.recv(2);
  c.call(3,'cua_alans_way_tabs',macFinished?{hangVm:true}:{hang:true});
  await until(()=>c.effects('wsr-tabs-3').length===1,'both tabs reads dispatched');await sleep(50);
  c.send({method:'notifications/cancelled',params:{requestId:3,reason:'Fixture stopped'}});
  await c.recv(3);
  const cancels=c.events().filter(e=>e.m?.method==='notifications/cancelled');
  assert.deepEqual(cancels.map(e=>[e.host,e.m.params.requestId]).sort(),macFinished?[['vm','wsr-tabs-3']]:[['mac',3],['vm','wsr-tabs-3']]);
  const calls=c.events().filter(e=>e.kind==='receive'&&e.m.method==='tools/call'&&[3,'wsr-tabs-3'].includes(e.m.id));
  assert.equal(calls.length,2);assert.ok(calls.every(e=>Number.isInteger(e.m.params._meta?.['alans-way/remainingMs'])));
  await sleep(50);assert.equal(c.messages.filter(m=>m.id===3).length,1);
});
test('pre-ready held cancellation answers once and never dispatches',async t=>{
  const c=client(t,'normal',{ROUTER_TEST_HOLD:'1'});
  await until(()=>fs.existsSync(path.join(c.dir,'restore-started')),'continuation pending');
  c.call(2,'cua_alans_way_open',{url:'https://example.invalid/ordinary'});
  c.send({method:'notifications/cancelled',params:{requestId:2,reason:'Fixture stopped'}});
  const reply=await c.recv(2);assert.equal(reply.result.isError,true);assert.match(JSON.stringify(reply),/cancel/i);
  c.init();await c.recv(1);await sleep(500);
  assert.equal(c.effects(2).length,0);assert.equal(c.messages.filter(m=>m.id===2).length,1);
  assert.equal(c.events().filter(e=>e.m?.method==='notifications/cancelled').length,0);
});
test('a never-written buffered write may dispatch once after continuation',async t=>{
  const c=client(t,'normal',{ROUTER_TEST_HOLD:'1'});
  await until(()=>fs.existsSync(path.join(c.dir,'restore-started')),'continuation pending');
  c.call(2,'cua_alans_way_open',{url:'https://example.invalid/ordinary'});c.init();await c.recv(1);
  await c.recv(2);assert.deepEqual(c.effects(2).map(e=>e.host),['vm']);
});

test('an unapproved write lost on the lazy VM reports uncertainty',async t=>{
  const c=client(t,'normal');c.init();await c.recv(1);
  c.call(2,'cua_alans_way_open',{host:'vm',url:'https://example.invalid/ordinary',die:true});
  const reply=await c.recv(2);
  assert.equal(reply.result.isError,true);assert.match(JSON.stringify(reply),/may or may not have happened.*not retried/i);
  assert.equal(c.effects(2).length,1);
});
for(const mode of ['retry','exit']) for(const write of [false,true]) test('cancelled '+(write?'write':'read')+' never replays on '+mode,async t=>{
  const c=client(t,mode,{ROUTER_TEST_IGNORE_CANCEL:'1',ROUTER_TEST_EXIT_MS:'200'});c.init();
  c.call(2,write?'cua_alans_way_open':'cua_alans_way_status',write?{url:'https://example.invalid/ordinary'}:{});
  await until(()=>c.effects(2).length===1,'call dispatched');
  c.send({method:'notifications/cancelled',params:{requestId:2}});
  const reply=await c.recv(2);assert.equal(reply.result.isError,true);assert.match(JSON.stringify(reply),/cancel/i);
  if(write)assert.match(JSON.stringify(reply),/may or may not have happened.*not retried/i);
  await c.recv(1);await sleep(100);assert.equal(c.effects(2).length,1);
  assert.equal(c.messages.filter(m=>m.id===2).length,1);
});
test('an expired read never dispatches on VM failover',async t=>{
  const c=client(t,'exit',{HERMES_ROUTER_CALL_HARD_MS:'3100',ROUTER_TEST_EXIT_MS:'200'});c.init();c.call(2,'cua_alans_way_status',{});
  const reply=await c.recv(2);assert.equal(reply.result.isError,true);assert.match(JSON.stringify(reply),/in time/);
  assert.equal(c.effects(2).length,1);
});
test('an expired never-written write does not dispatch after continuation',async t=>{
  const c=client(t,'normal',{ROUTER_TEST_HOLD:'1',HERMES_ROUTER_CALL_HARD_MS:'3100'});
  await until(()=>fs.existsSync(path.join(c.dir,'restore-started')),'continuation pending');
  c.call(2,'cua_alans_way_open',{url:'https://example.invalid/ordinary'});c.init();await c.recv(1);
  const reply=await c.recv(2);assert.equal(reply.result.isError,true);assert.match(JSON.stringify(reply),/in time.*may or may not have happened.*not retried/i);
  assert.equal(c.effects(2).length,0);
});

test('cancellation of a non-tool request reaches its backend',async t=>{
  const c=client(t,'normal');c.init();await c.recv(1);
  c.send({id:2,method:'tools/list',params:{hang:true}});
  await until(()=>c.events().some(e=>e.kind==='receive'&&e.m.id===2),'listing dispatched');
  c.send({method:'notifications/cancelled',params:{requestId:2}});await c.recv(2);
  const cancels=c.events().filter(e=>e.m?.method==='notifications/cancelled');
  assert.equal(cancels.length,1);assert.equal(cancels[0].host,'mac');assert.equal(cancels[0].m.params.requestId,2);
});
