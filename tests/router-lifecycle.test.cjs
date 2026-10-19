// Public process lifecycle tests. No private router imports or real host/SSH.
// Optional real SDK coverage: HERMES_EOF_CONNECTOR=/frozen/desktop/scripts/browser-mcp.cjs.
// EOF allows 1s for existing replies, then 1s for child EOF and 500ms for TERM
// before KILL. Tests allow 4s including process scheduling and stdout closure.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const readline = require('node:readline');
const { spawn } = require('node:child_process');
const router = process.env.HERMES_EOF_ROUTER || path.resolve(__dirname, '../alans-way/scripts/workspace-router.cjs');
const realConnector = process.env.HERMES_EOF_CONNECTOR;
const evidence = process.env.HERMES_EOF_EVIDENCE;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(read, message, ms = 4000) {
  const end = Date.now() + ms;
  while (!read()) { assert.ok(Date.now() < end, message); await delay(10); }
  return read();
}
function alive(pid) { try { process.kill(pid, 0); return true; } catch (e) { if (e.code === 'ESRCH') return false; throw e; } }
const auditSource = `
const fs = require('node:fs');
const log = (kind, data = {}) => fs.appendFileSync(process.env.EOF_AUDIT, JSON.stringify({
 at: Date.now(), kind, pid: process.pid, ppid: process.ppid, argv: process.argv,
 version: process.version, electron: process.env.ELECTRON_RUN_AS_NODE, ...data }) + '\\n');
log('start'); process.stdin.on('end', () => log('stdin-end'));
process.on('exit', code => log('process-exit', { code }));
// Public diagnostic subscription only: observe the router's real kernel
// child exit/close events without replacing spawn, kill, stdin or exit.
require('node:diagnostics_channel').channel('child_process').subscribe(({process:child}) => {
 child.on('exit', (code,signal) => log('child-exit', {childPid:child.pid,code,signal}));
 child.on('close', (code,signal) => log('child-close', {childPid:child.pid,code,signal}));
});
`;
const fixture = `
const fs = require('node:fs');
const log = (kind, data = {}) => fs.appendFileSync(process.env.EOF_FIXTURE_LOG,
 JSON.stringify({at:Date.now(),kind,pid:process.pid,...data})+'\\n');
const mode=process.env.EOF_MODE;
if(mode==='refuse-eof'||mode==='refuse-term') {
 setInterval(()=>{},1000);
 process.on('SIGTERM',()=>{log('term');if(mode==='refuse-eof')process.exit(0);});
}
require('node:readline').createInterface({input:process.stdin}).on('line', line=>{
 const m=JSON.parse(line);log('request',{m});if(m.id===undefined)return;
 const reply=()=>process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:m.id,result:
 m.method==='initialize'?{protocolVersion:'2024-11-05',capabilities:{tools:{}}}:
 {content:[{type:'text',text:JSON.stringify({ok:true,host:'vps',tabs:[]})}]}})+'\\n');
 if(m.method==='tools/call' && mode==='hang')return;
 if(m.method==='tools/call' && mode==='slow')return setTimeout(reply,150);
 reply();
});
`;
class Client {
  constructor(t, { real = false, mode = 'normal', dual = false, missingBot = false, missingScript = false, malformedConnection = false, missingSsh = false, copyRouter = false, continuation = false } = {}) {
    const parent = evidence || os.tmpdir(); fs.mkdirSync(parent, {recursive:true});
    this.dir = fs.mkdtempSync(path.join(parent, 'router-eof-'));
    this.traceFile = path.join(this.dir, 'trace.jsonl'); this.auditFile = path.join(this.dir, 'processes.jsonl');
    this.fixtureFile = path.join(this.dir, 'requests.jsonl');
    this.messages=[]; this.http=[]; this.next=1; this.closed=null; this.stderr=''; this.cleanupSignals=[];
    this.trace('case', {name:t.name, runtime:process.version, execPath:process.execPath, router, connector:real?realConnector:'owned fixture'});
    fs.mkdirSync(path.join(this.dir, 'home')); fs.mkdirSync(path.join(this.dir, 'bin'));
    fs.writeFileSync(path.join(this.dir, 'audit.cjs'), auditSource);
    fs.writeFileSync(path.join(this.dir, 'connector.cjs'), fixture);
    const connector = missingScript ? path.join(this.dir, 'missing.cjs') : real ? realConnector : path.join(this.dir, 'connector.cjs');
    this.connection = path.join(this.dir, 'home/connection.json');
    // The executable named ssh is exclusively an owned exec shim; it never
    // contacts a host, opens a socket or interprets the router's SSH command.
    fs.writeFileSync(path.join(this.dir, 'bin/ssh'), '#!/bin/sh\nexec "$EOF_NODE" "$EOF_CONNECTOR" --bot-id eof-owned --connection "$EOF_CONNECTION"\n', {mode:0o755});
    const state = path.join(this.dir, 'home/state.json');
    this.state=state;
    if (dual || continuation) fs.writeFileSync(state, JSON.stringify({state:continuation?'offline':'online',since:new Date().toISOString(),lastSeenOnline:new Date().toISOString()}));
    if (continuation) {
      fs.writeFileSync(path.join(this.dir,'home/router-last-self-probe'),String(Date.now()));
      fs.writeFileSync(path.join(this.dir,'home/resume-url-eof-owned.json'),JSON.stringify({url:'https://fixture.example/',at:Date.now()}));
    }
    this.runtimeRouter=copyRouter?path.join(this.dir,'router.cjs'):router;
    if(copyRouter){fs.copyFileSync(router,this.runtimeRouter);fs.copyFileSync(path.join(path.dirname(router),'commit-patterns.json'),path.join(this.dir,'commit-patterns.json'));}
    if(missingSsh)fs.rmSync(path.join(this.dir,'bin/ssh'));
    const env = {PATH:path.join(this.dir,'bin')+(missingSsh?'':path.delimiter+process.env.PATH),
      HOME:path.join(this.dir,'home'),TMPDIR:path.join(this.dir,'home'),XDG_CONFIG_HOME:path.join(this.dir,'home'),
      XDG_DATA_HOME:path.join(this.dir,'home'),APPDATA:path.join(this.dir,'home'),
      ELECTRON_RUN_AS_NODE:'1',NODE_OPTIONS:'--require='+path.join(this.dir,'audit.cjs'),EOF_AUDIT:this.auditFile,
      EOF_FIXTURE_LOG:this.fixtureFile,EOF_MODE:mode,EOF_NODE:process.execPath,EOF_CONNECTOR:connector,EOF_CONNECTION:this.connection};
    this.server=http.createServer((req,res)=>{
      const row={method:req.method,path:req.url,bot:req.headers['x-hermes-bot'],authenticated:req.headers.authorization==='Bearer eof-owned-token'};
      this.http.push(row);this.trace('http',row);
      assert.equal(row.authenticated,true);assert.equal(row.bot,'eof-owned');
      const respond=()=>{res.setHeader('Content-Type','application/json');res.end(JSON.stringify({ok:true,host:'vps',computer:false,tabs:[]}));};
      if(continuation && req.url==='/v1/restore') {
        this.releaseRestore=()=>{res.statusCode=404;respond();};return;
      }
      if(continuation && req.url==='/v1/tabs') {
        this.releaseTabs=respond;return;
      }
      if(this.httpDelay==='hang')return;
      if(this.httpDelay)setTimeout(respond,this.httpDelay);else respond();
    });
    this.started=new Promise(resolve=>this.server.listen(0,'127.0.0.1',()=>{
      const endpoint='http://127.0.0.1:'+this.server.address().port;
      fs.writeFileSync(this.connection, malformedConnection ? '{' : JSON.stringify({url:endpoint,token:'eof-owned-token'}));this.trace('endpoint',{endpoint});
      this.p=spawn(process.execPath,[this.runtimeRouter,...(missingBot?[]:['--bot-id','eof-owned']),
        '--vps-script',connector,'--vps-connection',this.connection,'--mac-state-file',state,
        ...((dual||continuation)?['--mac-ssh','owned-exec-shim','--mac-script','/owned/browser-mcp.cjs']:[])],{env,stdio:['pipe','pipe','pipe']});
      this.trace('router-spawn',{pid:this.p.pid,runtimeRouter:this.runtimeRouter});
      this.p.stdin.on('error',e=>this.trace('stdin-error',{code:e.code}));
      this.p.stderr.on('data',b=>{this.stderr+=b;this.trace('stderr',{text:String(b)});});
      this.p.stdout.on('data',b=>this.trace('stdout',{text:String(b)}));
      readline.createInterface({input:this.p.stdout}).on('line',line=>this.messages.push(JSON.parse(line)));
      this.p.on('close',(code,signal)=>{this.closed={code,signal};this.trace('router-close',this.closed);});
      resolve();
    }));
    t.after(async()=>{
      await this.started;
      if(!this.closed){this.cleanupSignals.push('router SIGKILL');this.trace('harness-cleanup',{pid:this.p.pid,signal:'SIGKILL'});this.p.kill('SIGKILL');await until(()=>this.closed,'owned router cleanup');}
      for(const leaf of this.leaves())if(alive(leaf.pid)){this.cleanupSignals.push('leaf SIGKILL');this.trace('harness-cleanup',{pid:leaf.pid,signal:'SIGKILL'});process.kill(leaf.pid,'SIGKILL');await until(()=>!alive(leaf.pid),'owned leaf cleanup');}
      this.server.closeAllConnections?.();await new Promise(r=>this.server.close(r));
      fs.rmSync(this.connection,{force:true});
      this.trace('cleanup-complete',{signals:this.cleanupSignals,leafPids:this.leaves().map(p=>p.pid)});
      if(!evidence)fs.rmSync(this.dir,{recursive:true,force:true});
    });
  }
  trace(kind,data={}){fs.appendFileSync(this.traceFile,JSON.stringify({at:Date.now(),kind,...data})+'\n');}
  audit(){return fs.existsSync(this.auditFile)?fs.readFileSync(this.auditFile,'utf8').trim().split('\n').filter(Boolean).map(JSON.parse):[];}
  leaves(){return this.audit().filter(e=>e.kind==='start'&&e.pid!==this.p?.pid);}
  requests(){return fs.existsSync(this.fixtureFile)?fs.readFileSync(this.fixtureFile,'utf8').trim().split('\n').filter(Boolean).map(JSON.parse):[];}
  send(m){this.trace('client-write',{m});this.p.stdin.write(JSON.stringify(m)+'\n');}
  request(method,params){const id=this.next++;this.send({jsonrpc:'2.0',id,method,params});return id;}
  async recv(id){return until(()=>this.messages.find(m=>m.id===id),'missing reply '+id+': '+this.stderr);}
  async ready(){await this.started;const id=this.request('initialize',{protocolVersion:'2024-11-05',capabilities:{},clientInfo:{name:'eof-owned',version:'1'}});assert.ok((await this.recv(id)).result);this.send({jsonrpc:'2.0',method:'notifications/initialized'});}
  read(args={}){return this.request('tools/call',{name:'cua_alans_way_status',arguments:args});}
  eof(final){this.eofAt=Date.now();this.trace('client-eof',{final});this.p.stdin.end(final);}
  async exited(code=0,leafCount=1,{natural=true}={}){
    await until(()=>this.closed,'router must close within the 4s public EOF bound');
    assert.deepEqual(this.closed,{code,signal:null});
    assert.equal(this.leaves().length,leafCount,'no unexpected connector spawn or restart');
    for(const leaf of this.leaves()){
      assert.equal(leaf.electron,'1');assert.equal(leaf.version,process.version);
      assert.equal(alive(leaf.pid),false,'owned connector must be reaped before router closes');
      assert.ok(this.audit().some(e=>e.kind==='child-exit'&&e.childPid===leaf.pid&&e.pid===this.p.pid),'router observed positive kernel child exit');
      assert.ok(this.audit().some(e=>e.kind==='child-close'&&e.childPid===leaf.pid&&e.pid===this.p.pid),'router observed child stdio closure');
      if(natural){assert.ok(this.audit().some(e=>e.kind==='stdin-end'&&e.pid===leaf.pid),'leaf received real EOF');assert.ok(this.audit().some(e=>e.kind==='process-exit'&&e.pid===leaf.pid&&e.code===0),'leaf recorded normal exit');}
    }
    assert.equal(this.cleanupSignals.length,0,'harness cleanup cannot count as EOF success');
    if(this.eofAt)assert.ok(Date.now()-this.eofAt<4000);
  }
}

for(const real of [false,true]) {
  const options=real&&!realConnector?{skip:'Set HERMES_EOF_CONNECTOR to a frozen real connector'}:{};
  const label=real?'real SDK connector':'owned connector';
  test(label+': open parent remains usable, then quiescent EOF closes both',options,async t=>{
    const c=new Client(t,{real});await c.ready();assert.ok((await c.recv(c.read())).result);
    await delay(150);assert.equal(c.closed,null);assert.equal(c.audit().filter(e=>e.kind==='stdin-end').length,0);
    assert.ok((await c.recv(c.read())).result);c.eof();await c.exited();
    assert.equal(c.messages.filter(m=>m.result).length,3);
    if(real)assert.equal(c.http.length,2);
  });
  for(const lf of [true,false])test(label+': final read and EOF in one write '+(lf?'with LF':'without LF'),options,async t=>{
    const c=new Client(t,{real});await c.ready();const id=c.next++;
    c.eof(JSON.stringify({jsonrpc:'2.0',id,method:'tools/call',params:{name:'cua_alans_way_status',arguments:{}}})+(lf?'\n':''));
    assert.ok((await c.recv(id)).result);await c.exited();assert.equal(c.messages.filter(m=>m.id===id).length,1);
    if(real)assert.equal(c.http.length,1);else assert.equal(c.requests().filter(e=>e.m.id===id).length,1);
  });
  test(label+': pending ordinary read drains before child EOF',options,async t=>{
    const c=new Client(t,{real,mode:'slow'});await c.ready();c.httpDelay=150;const id=c.read();
    await until(()=>real?c.http.length===1:c.requests().some(e=>e.m.id===id),'read reached owned backend');c.eof();
    assert.ok((await c.recv(id)).result);await c.exited();assert.equal(c.messages.filter(m=>m.id===id).length,1);
    if(real)assert.equal(c.http.length,1);
  });
}
test('unanswered ordinary read reports cancellation within drain bound without replay',async t=>{
  const c=new Client(t,{mode:'hang'});await c.ready();const id=c.read();await until(()=>c.requests().some(e=>e.m.id===id),'read reached leaf');c.eof();
  const m=await c.recv(id);assert.equal(m.result.isError,true);assert.match(m.result.content[0].text,/cancel|closed/i);
  await c.exited();assert.equal(c.requests().filter(e=>e.m.id===id).length,1);assert.equal(c.messages.filter(m=>m.id===id).length,1);
});
for(const mode of ['refuse-eof','refuse-term'])test(mode+': bounded owned cleanup leaves no child',async t=>{
  const c=new Client(t,{mode});await c.ready();await c.recv(c.read());c.eof();await c.exited(1,1,{natural:false});
  assert.ok(c.audit().some(e=>e.kind==='stdin-end'&&e.pid===c.leaves()[0].pid));
  assert.ok(c.requests().some(e=>e.kind==='term'),'owned child observed TERM');
});
test('EOF settles active and lazy VM connectors without failover or restart',async t=>{
  const c=new Client(t,{dual:true});await c.ready();await c.recv(c.read());await c.recv(c.read({host:'vm'}));
  c.eof();await c.exited(0,2);assert.equal(c.requests().filter(e=>e.m?.method==='tools/call').length,2);
  assert.doesNotMatch(c.stderr,/backend exited.*routing|retrying the spawn|online.*exiting/);
});
for(const signal of ['SIGTERM','SIGINT','SIGHUP'])test(signal+': owns and reaps both connectors',async t=>{
  const c=new Client(t,{dual:true});await c.ready();await c.recv(c.read({host:'vm'}));
  c.trace('client-signal',{signal});c.p.kill(signal);await c.exited(1,2,{natural:false});
});
test('missing required bot config exits nonzero without spawning a connector',async t=>{
  const c=new Client(t,{missingBot:true});await c.started;c.eof();await c.exited(1,0);assert.match(c.stderr,/bot-id.*required/);
});
test('unavailable connector script exits nonzero without an orphan',async t=>{
  const c=new Client(t,{missingScript:true});await c.started;c.eof();await c.exited(1,1,{natural:false});assert.match(c.stderr,/MODULE_NOT_FOUND/);
});
test('malformed explicit connection returns a public error and closes normally',{skip:realConnector?false:'Set HERMES_EOF_CONNECTOR to a frozen real connector'},async t=>{
  const c=new Client(t,{real:true,malformedConnection:true});await c.ready();const m=await c.recv(c.read());assert.equal(m.result.isError,true);c.eof();await c.exited();assert.equal(c.http.length,0);
});

test('real pending read that never answers is honestly cancelled and its connector reaped',{skip:realConnector?false:'Set HERMES_EOF_CONNECTOR to a frozen real connector'},async t=>{
  const c=new Client(t,{real:true});await c.ready();c.httpDelay='hang';const id=c.read();await until(()=>c.http.length===1,'read reached owned HTTP endpoint');c.eof();
  const m=await c.recv(id);assert.equal(m.result.isError,true);assert.match(m.result.content[0].text,/cancel|closed/i);
  await c.exited(1,1,{natural:false});assert.equal(c.http.length,1);assert.equal(c.messages.filter(m=>m.id===id).length,1);
});
test('backend spawn ENOENT falls back before EOF and settles without retry after EOF',async t=>{
  const c=new Client(t,{dual:true,missingSsh:true});await c.ready();await c.recv(c.read());c.eof();await c.exited();assert.match(c.stderr,/failed to spawn backend.*ENOENT/);
});
test('script replacement preserves clean exit status and waits for owned connectors',async t=>{
  const c=new Client(t,{dual:true,copyRouter:true});await c.ready();await c.recv(c.read({host:'vm'}));
  await delay(1500);const future=new Date(Date.now()+10000);fs.utimesSync(c.runtimeRouter,future,future);
  await c.exited(0,2,{natural:false});assert.match(c.stderr,/script replaced/);
});
test('EOF prevents source reload and offline failover while owned children refuse shutdown',async t=>{
  const c=new Client(t,{dual:true,copyRouter:true,mode:'refuse-term'});await c.ready();await c.recv(c.read({host:'vm'}));
  await delay(4100);const future=new Date(Date.now()+10000);fs.utimesSync(c.runtimeRouter,future,future);
  fs.writeFileSync(c.state,JSON.stringify({state:'offline',since:new Date().toISOString()}));
  c.eof();await c.exited(1,2,{natural:false});assert.doesNotMatch(c.stderr,/script replaced|routing to VPS|retrying the spawn/);
});
for(const phase of ['restore','tabs'])test('EOF stops continuation after pending '+phase+' without an automatic open or restart',async t=>{
  const c=new Client(t,{continuation:true,mode:'refuse-eof'});await c.ready();await until(()=>c.releaseRestore,'owned restore request arrived');
  if(phase==='tabs'){c.releaseRestore();await until(()=>c.releaseTabs,'owned tabs read arrived');}
  c.eof();await until(()=>c.audit().some(e=>e.pid===c.p.pid&&e.kind==='stdin-end'),'router received terminal EOF');if(phase==='restore')c.releaseRestore();else c.releaseTabs();
  await c.exited(1,1,{natural:false});
  assert.deepEqual(c.http.map(e=>[e.method,e.path]),phase==='restore'?[['POST','/v1/restore']]:[['POST','/v1/restore'],['GET','/v1/tabs']]);
  assert.equal(c.requests().filter(e=>e.m?.method==='initialize').length,1);
});

test('real active and lazy VM connectors both receive EOF and exit without a respawn',{skip:realConnector?false:'Set HERMES_EOF_CONNECTOR to a frozen real connector'},async t=>{
  const c=new Client(t,{dual:true,real:true});await c.ready();await c.recv(c.read());await c.recv(c.read({host:'vm'}));
  c.eof();await c.exited(0,2);assert.equal(c.http.length,2);assert.ok(c.http.every(e=>e.method==='GET'&&e.path==='/v1/status'));
});
test('signal during a pending read reports shutdown without claiming client EOF',async t=>{
  const c=new Client(t,{mode:'hang'});await c.ready();const id=c.read();await until(()=>c.requests().some(e=>e.m?.id===id),'read reached owned leaf');
  c.p.kill('SIGTERM');const m=await c.recv(id);assert.equal(m.result.isError,true);assert.match(m.result.content[0].text,/cancel|shutdown/i);assert.doesNotMatch(m.result.content[0].text,/Client input closed/);
  await c.exited(1,1,{natural:false});
});
