// Public stdio protocol tests. The connector fixture deliberately uses legacy
// Node readline, so these also protect compatibility at the router-owned seam.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const router = process.env.HERMES_FRAMING_ROUTER || path.resolve(__dirname, '../alans-way/scripts/workspace-router.cjs');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

const connector = String.raw`
const fs = require('node:fs');
let queue=Promise.resolve();
require('node:readline').createInterface({input:process.stdin}).on('line', line => {
  let m; try { m=JSON.parse(line); } catch { return; }
  fs.appendFileSync(process.env.FRAME_LOG, JSON.stringify(m)+'\n');
  if (m.id === undefined) return;
  const a=m.params?.arguments || {};
  let value={echo:m.params, text:a.reply || 'ready', host:process.env.FRAME_HOST || 'vm'};
  if(m.params?.name==='cua_alans_way_open')value={...value,id:'frame-tab',epoch:1,url:'https://fixture.example/'};
  if(m.params?.name==='cua_alans_way_snapshot')value={...value,url:'https://fixture.example/',generation:1,tab:{id:'frame-tab',epoch:1},approvalContext:{version:1,documentId:'a'.repeat(32),url:'https://fixture.example/'},elements:[{ref:'e1',role:'button',name:'Place\u2028order\u2029🌿',approvalTarget:'b'.repeat(32)}],truncated:{text:false,elements:false},iframes:[]};
  if(m.params?.name==='cua_alans_way_tabs')value={tabs:[{id:process.env.FRAME_HOST==='computer'?'computer-tab':'vm-tab',url:'https://fixture.example/',epoch:1}]};
  const result=m.method==='initialize' ? {protocolVersion:'2024-11-05', capabilities:{}}
    : {content:[{type:'text',text:JSON.stringify(value)}]};
  const wire=Buffer.from(JSON.stringify({jsonrpc:'2.0',id:m.id,result})+(a.crlf?'\r\n':'\n'));
  queue=queue.then(async()=>{
    if(a.malformed || (a.malformedVm && process.env.FRAME_HOST!=='computer')) {
      process.stdout.write(a.idless?'{"broken":\n':'{"jsonrpc":"2.0","id":'+JSON.stringify(m.id)+',"result":INVALID}\n');
      if(a.late)setTimeout(()=>process.stdout.write(wire),20);
      return;
    }
    if(a.noise)process.stdout.write('{"broken":\n');
    if(a.fragment) { for(let i=0;i<wire.length;i++) {process.stdout.write(wire.subarray(i,i+1)); await new Promise(r=>setTimeout(r,1));} }
    else process.stdout.write(wire);
  });
});
`;

class Client {
  constructor(t, computer=false) {
    this.dir=fs.mkdtempSync(path.join(os.tmpdir(),'router-framing-'));
    fs.writeFileSync(path.join(this.dir,'connector.cjs'),connector);
    this.log=path.join(this.dir,'calls.jsonl');
    fs.mkdirSync(path.join(this.dir,'bin'));
    fs.writeFileSync(path.join(this.dir,'bin/ssh'),'#!/bin/sh\nfor last in "$@"; do :; done\ncase "$last" in\n *conn_script*) printf %s /fixture/browser-mcp.cjs ;;\n *) FRAME_HOST=computer exec "$FRAME_NODE" "$FRAME_CONNECTOR" ;;\nesac\n',{mode:0o755});
    this.messages=[]; this.wire=[]; this.buffer=Buffer.alloc(0); this.next=1;
    this.p=spawn(process.execPath,[router,'--bot-id','framing-test','--vps-script',path.join(this.dir,'connector.cjs'),
      '--vps-connection',path.join(this.dir,'connection.json'),'--mac-state-file',path.join(this.dir,'mac.json'),
      ...(computer?['--mac-ssh','fixture-only','--mac-script','/fixture/browser-mcp.cjs']:[])],
      {env:{...process.env,HERMES_WORKSPACE_MAC_SSH:'',FRAME_LOG:this.log,FRAME_NODE:process.execPath,FRAME_CONNECTOR:path.join(this.dir,'connector.cjs'),PATH:path.join(this.dir,'bin')+path.delimiter+process.env.PATH},stdio:['pipe','pipe','pipe']});
    this.stderr=''; this.p.stderr.on('data',b=>this.stderr+=b);
    this.p.stdout.on('data',chunk=>{
      this.buffer=Buffer.concat([this.buffer,chunk]); let at;
      while((at=this.buffer.indexOf(10))>=0) {
        const line=this.buffer.subarray(0,at).toString('utf8'); this.buffer=this.buffer.subarray(at+1);
        this.wire.push(line); try {this.messages.push(JSON.parse(line));} catch { assert.fail('invalid router output: '+line); }
      }
    });
    t.after(async()=>{this.p.kill(); await new Promise(r=>this.p.exitCode!==null?r():this.p.once('exit',r)); fs.rmSync(this.dir,{recursive:true,force:true});});
  }
  send(method,params,options={}) {
    const id=options.id ?? this.next++; const m={jsonrpc:'2.0',id,method,params};
    let wire=JSON.stringify(m);
    if(options.escaped)wire=wire.replace(/[\u2028\u2029]/g,c=>'\\u'+c.charCodeAt(0).toString(16));
    this.p.stdin.write(Buffer.from(wire+(options.crlf?'\r\n':'\n')));
    return id;
  }
  async recv(id) {
    for(let i=0;i<150;i++) {const at=this.messages.findIndex(m=>m.id===id);if(at>=0)return this.messages.splice(at,1)[0];await pause(10);}
    assert.fail('router did not answer request '+id+'; stderr='+this.stderr);
  }
  async ready(){await this.recv(this.send('initialize',{protocolVersion:'2024-11-05',capabilities:{},clientInfo:{name:'framing',version:'1'}}));}
  calls(){return fs.readFileSync(this.log,'utf8').trim().split('\n').map(JSON.parse);}
}

test('literal UTF8 U+2028/U+2029 client request answers once through a legacy connector', async t=>{
  const c=new Client(t); await c.ready();
  const value='Read'+String.fromCodePoint(0x2028)+'guide'+String.fromCodePoint(0x2029)+'🌿';
  const id=c.send('framing/echo',{value});
  const response=await c.recv(id);
  assert.deepEqual(JSON.parse(response.result.content[0].text).echo,{value});
  const calls=fs.readFileSync(c.log,'utf8').trim().split('\n').map(JSON.parse);
  assert.equal(calls.filter(m=>m.id===id).length,1);
});

for(const backend of ['active VPS','active computer','lazy VM']) {
  test(backend+' literal child response survives multibyte fragmentation and legacy client parsing',async t=>{
    const c=new Client(t,backend!=='active VPS');await c.ready();
    const legacy=[];
    require('node:readline').createInterface({input:c.p.stdout}).on('line',line=>legacy.push(JSON.parse(line)));
    const value='Read'+String.fromCodePoint(0x2028)+'guide'+String.fromCodePoint(0x2029)+'🌿';
    const id=c.send('tools/call',{name:'cua_alans_way_status',arguments:{...(backend==='lazy VM'?{host:'vm'}:{}),reply:value,fragment:true,crlf:true}}, {id:'req'+value,crlf:true,escaped:true});
    const r=await c.recv(id);
    assert.equal(JSON.parse(r.result.content[0].text).text,value);
    assert.equal(JSON.parse(r.result.content[0].text).host,backend==='active computer'?'computer':'vm');
    assert.equal(legacy.filter(m=>m.id===id).length,1);
    assert.ok(c.wire.every(line=>!/[\u2028\u2029]/.test(line)), 'legacy clients must see escaped separators');
    assert.equal(c.calls().filter(m=>m.id===id).length,1);
  });
}

test('malformed lazy VM half of merged tabs answers explicitly and the next merged read recovers',async t=>{
  const c=new Client(t,true);await c.ready();
  await c.recv(c.send('tools/call',{name:'cua_alans_way_status',arguments:{host:'vm'}}));
  const id=c.send('tools/call',{name:'cua_alans_way_tabs',arguments:{malformedVm:true}});
  assert.equal((await c.recv(id)).result.isError,true);
  const next=c.send('tools/call',{name:'cua_alans_way_tabs',arguments:{}});
  const tabs=JSON.parse((await c.recv(next)).result.content[0].text).tabs;
  assert.deepEqual(tabs.map(t=>t.id).sort(),['computer-tab','vm-tab']);
  assert.ok(c.calls().some(m=>m.id==='wsr-tabs-'+id),'real lazy VM merge path reached');
});

test('literal handshake, approval, Unicode IDs and cancellation preserve exactly one forward',async t=>{
  const c=new Client(t);
  const initId='initialize\u2028\u2029🌿';
  await c.recv(c.send('initialize',{protocolVersion:'2024-11-05',capabilities:{elicitation:{}},clientInfo:{name:'client\u2028\u2029🌿',version:'1'}},{id:initId}));
  c.p.stdin.write(JSON.stringify({jsonrpc:'2.0',method:'notifications/initialized'})+'\n');
  await c.recv(c.send('tools/call',{name:'cua_alans_way_open',arguments:{url:'https://fixture.example/'}}));
  await c.recv(c.send('tools/call',{name:'cua_alans_way_snapshot',arguments:{tabId:'frame-tab'}}));
  const params={name:'cua_alans_way_action',arguments:{tabId:'frame-tab',epoch:1,action:'click',name:'Place\u2028order\u2029🌿',commit:{kind:'purchase',summary:'One\u2028draft\u2029🌿'}}};
  const actionId=c.send('tools/call',params,{id:'action\u2028\u2029🌿'});
  const approval=await c.recv('wsr-commit-1');assert.equal(approval.method,'elicitation/create');
  const answer={jsonrpc:'2.0',id:approval.id,result:{action:'accept',content:{approve:true,note:'yes\u2028\u2029'}}};
  c.p.stdin.write(JSON.stringify(answer)+'\n'+JSON.stringify(answer)+'\n');
  await c.recv(actionId);
  assert.equal(c.calls().filter(m=>m.id===actionId).length,1);
  assert.ok(c.calls().find(m=>m.id===actionId).params.arguments.approval.binding);
  const cancelId=c.send('tools/call',params,{id:'cancel\u2028\u2029🌿'});
  const cancelApproval=await c.recv('wsr-commit-2');
  c.p.stdin.write(JSON.stringify({jsonrpc:'2.0',method:'notifications/cancelled',params:{requestId:cancelId}})+'\n'+JSON.stringify({...answer,id:cancelApproval.id})+'\n');
  await c.recv(c.send('framing/echo',{barrier:true}));
  assert.equal(c.calls().filter(m=>m.id===cancelId).length,0);
  assert.ok(c.calls().some(m=>m.id===initId),'Unicode handshake ID reaches backend');
});

test('escaped equivalents, NBSP, CRLF and several frames in fragmented UTF8 chunks preserve values and IDs',async t=>{
  const c=new Client(t);await c.ready();
  const values=['a\u2028b','a\u2029b','a\u00a0b','🌿é'];
  const ids=values.map(value=>c.send('framing/echo',{value},{escaped:true,crlf:true}));
  for(let i=0;i<ids.length;i++)assert.equal(JSON.parse((await c.recv(ids[i])).result.content[0].text).echo.value,values[i]);
  const first={jsonrpc:'2.0',id:90,method:'framing/echo',params:{value:'🌿\u2028é\u2029'}};
  const second={jsonrpc:'2.0',id:91,method:'framing/echo',params:{value:'next'}};
  const wire=Buffer.from(JSON.stringify(first)+'\r\n'+JSON.stringify(second)+'\n');
  assert.ok(wire.includes(Buffer.from([0xe2,0x80,0xa8])),'literal U+2028 bytes are on the wire');
  for(let i=0;i<wire.length;i++) {c.p.stdin.write(wire.subarray(i,i+1));await pause(1);}
  assert.equal(JSON.parse((await c.recv(90)).result.content[0].text).echo.value,first.params.value);
  assert.equal(JSON.parse((await c.recv(91)).result.content[0].text).echo.value,'next');
});

test('malformed client frame answers parse error and preserves following valid frames',async t=>{
  const c=new Client(t);await c.ready();
  c.p.stdin.write('{"bad":\n'+JSON.stringify({jsonrpc:'2.0',id:80,method:'framing/echo',params:{value:'after'}})+'\n');
  assert.equal((await c.recv(null)).error.code,-32700);
  assert.equal(JSON.parse((await c.recv(80)).result.content[0].text).echo.value,'after');
  assert.equal(c.calls().filter(m=>m.id===80).length,1);
});

for(const backend of ['active VPS','active computer','lazy VM']) {
  test(backend+' malformed response fails an uncertain action without replay and allows recovery',async t=>{
    const c=new Client(t,backend!=='active VPS');await c.ready();
    const args={...(backend==='lazy VM'?{host:'vm'}:{}),malformed:true,late:true,idless:backend==='active VPS'};
    const id=c.send('tools/call',{name:'cua_alans_way_open',arguments:{...args,url:'https://guide.example/'}});
    const r=await c.recv(id);
    assert.equal(r.result.isError,true);
    assert.match(r.result.content[0].text,/may.*happened.*not retried/i);
    const read=c.send('tools/call',{name:'cua_alans_way_status',arguments:{...(backend==='lazy VM'?{host:'vm'}:{})}});
    assert.equal(JSON.parse((await c.recv(read)).result.content[0].text).text,'ready');
    assert.equal(c.calls().filter(m=>m.id===id).length,1);
    await pause(30);assert.equal(c.messages.filter(m=>m.id===id).length,0,'a late valid response cannot answer the failed action twice');
  });
}
