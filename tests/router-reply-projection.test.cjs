// Public stdio regression: a real router process must retain approval proof
// internally while returning the documented browser state to ordinary clients.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const readline = require('node:readline');
const router = process.env.HERMES_REPLY_ROUTER || path.resolve(__dirname, '../alans-way/scripts/workspace-router.cjs');
const context = { version: 1, documentId: 'a'.repeat(32), url: 'https://fixture.example/' };
const control = { ref: 'e1', role: 'button', name: 'Place\u2028order\u2029🌿', approvalTarget: 'b'.repeat(32) };
const user = { approvalContext: { ...context, documentId: 'c'.repeat(32) }, approvalTarget: 'customer data', elements: [{ ref: 'business', role: 'button', approvalTarget: 'd'.repeat(32) }], results: [{ approvalContext: context, elements: [control] }] };
const tab = { id: 'reply-tab', epoch: 7, controller: 'agent', ownerBotId: 'reply-test', handback: null };
const page = { title: 'Fixture 🌿', url: context.url, text: 'Read\u2028page\u2029🌿', generation: 3, tab, approvalContext: context, elements: [control], truncated: { text: false, elements: false }, iframes: [] };
const link = { ref: 'e55', role: 'a', name: 'Charles Babbage', row: 'Computing pioneers', href: 'https://fixture.example/babbage' };
const actionLink = { ref: 'e56', role: 'a', name: 'Saved item', href: 'https://fixture.example/cart/delete?item=3', approvalTarget: 'c'.repeat(32) };

const connector = `
const fs=require('node:fs');
const context=${JSON.stringify(context)}, control=${JSON.stringify(control)}, user=${JSON.stringify(user)}, tab=${JSON.stringify(tab)}, page=${JSON.stringify(page)}, link=${JSON.stringify(link)}, actionLink=${JSON.stringify(actionLink)};
require('node:readline').createInterface({input:process.stdin}).on('line',line=>{
 const m=JSON.parse(line);fs.appendFileSync(process.env.REPLY_LOG,JSON.stringify(m)+'\\n');if(m.id===undefined)return;
 const a=m.params?.arguments||{};let data=page;
 if(a.variant==='changed')data={approvalContext:context,changed:[control],removed:['e8'],generation:4,tab,effect:{navigated:false,changed:true,text:'new 🌿',value:user},unlisted:9,continuedTab:tab.id,continuedEpoch:7};
 if(a.variant==='unchanged')data={approvalContext:context,unchanged:true,generation:3,tab,loading:false,overlays:[{name:'Banner'}]};
 if(a.variant==='eval')data={approvalContext:context,generation:3,tab,effect:{navigated:false,changed:false,text:''},value:user};
 if(a.variant==='batch')data={approvalContext:context,generation:3,tab,effect:{navigated:false,changed:false,text:''},results:[{ok:true,value:user,approvalContext:context,elements:[control]},{ok:false,error:'kept error',approvalContext:'business error detail'}],dispatched:true};
 if(a.variant==='old')data={...page};if(a.variant==='old'){delete data.approvalContext;data.elements=[{ref:'e1',role:'button',name:'Place order'}];}
 if(a.variant==='unknown')data={...page,approvalContext:{...context,version:2}};
 if(a.variant==='user')data=user;if(a.variant==='userPage')data=page;if(a.variant==='large')data={...page,text:'x'.repeat(110000)};
 if(a.variant==='open-page')data={...page,elements:a.maxElements===1?[control]:[control,link,actionLink],truncated:{text:false,elements:a.maxElements===1}};
 if(m.params?.name==='cua_alans_way_open'){
   const observation={...page,elements:[control,link,actionLink]};
   if(a.variant==='partial'||a.variant==='loading'){observation.elements=[link];observation.truncated={text:false,elements:a.variant==='partial'};observation.loading=a.variant==='loading';}
   if(a.variant==='wrong-tab')observation.tab={...tab,id:'other-tab'};
   if(a.variant==='new-document'){observation.approvalContext={...context,documentId:'d'.repeat(32)};observation.elements=[];observation.truncated={text:false,elements:true};}
   if(a.variant==='tab-url'){delete observation.url;observation.tab={...tab,url:context.url};}
   if(a.variant==='challenge')observation.challenge={kind:'recaptcha',blocking:true};
   if(a.variant==='large')observation.text='x'.repeat(110000);
   data=a.snapshot===true?{...tab,url:'https://fixture.example/before-redirect',...(a.variant==='read-error'?{observationError:'Page observation did not complete'}:{observation})}:tab;
 }
 const result=m.method==='initialize'?{protocolVersion:'2025-06-18',capabilities:{tools:{}}}:a.variant==='error'?{isError:true,content:[{type:'text',text:JSON.stringify(data)}],_meta:{browserRequest:{status:409,code:'ownership_changed'}}}:{content:[{type:'text',text:JSON.stringify(data)}],_meta:{custom:{retained:true}}};
 process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:m.id,result}).replace(/[\\u2028\\u2029]/g,c=>'\\\\u'+c.charCodeAt(0).toString(16))+'\\n');
});
`;

class Client {
  constructor(t, computer=false, desktop=false) {
    this.dir=fs.mkdtempSync(path.join(os.tmpdir(),'router-reply-'));this.log=path.join(this.dir,'calls.jsonl');
    fs.writeFileSync(path.join(this.dir,'connector.cjs'),connector);
    fs.mkdirSync(path.join(this.dir,'bin'));fs.writeFileSync(path.join(this.dir,'bin/ssh'),'#!/bin/sh\nfor last in "$@"; do :; done\ncase "$last" in\n *conn_script*) printf %s /fixture/browser-mcp.cjs ;;\n *) exec "$REPLY_NODE" "$REPLY_CONNECTOR" ;;\nesac\n',{mode:0o755});
    this.p=spawn(process.execPath,[router,'--bot-id','reply-test','--vps-script',path.join(this.dir,'connector.cjs'),'--vps-connection',path.join(this.dir,'connection.json'),'--mac-state-file',path.join(this.dir,'mac.json'),...(computer?['--mac-ssh','fixture-only','--mac-script','/fixture/browser-mcp.cjs']:[])],{env:{...process.env,HERMES_HOME:path.join(this.dir,'profile'),HERMES_WORKSPACE_MAC_SSH:'',HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS:desktop?'1':'',REPLY_LOG:this.log,REPLY_NODE:process.execPath,REPLY_CONNECTOR:path.join(this.dir,'connector.cjs'),PATH:path.join(this.dir,'bin')+path.delimiter+process.env.PATH},stdio:['pipe','pipe','pipe']});
    this.next=1;this.messages=[];this.stderr='';this.p.stderr.on('data',b=>this.stderr+=b);
    readline.createInterface({input:this.p.stdout}).on('line',line=>this.messages.push(JSON.parse(line)));
    t.after(async()=>{this.p.kill();await new Promise(r=>this.p.exitCode!==null?r():this.p.once('exit',r));fs.rmSync(this.dir,{recursive:true,force:true});});
  }
  send(m){this.p.stdin.write(JSON.stringify(m)+'\n');}
  async recv(id){for(let i=0;i<200;i++){const at=this.messages.findIndex(m=>m.id===id);if(at>=0)return this.messages.splice(at,1)[0];await new Promise(r=>setTimeout(r,5));}assert.fail('No reply '+id+': '+this.stderr);}
  async rpc(method,params){const id=this.next++;this.send({jsonrpc:'2.0',id,method,params});return this.recv(id);}
  call(name,args={}){return this.rpc('tools/call',{name:'cua_alans_way_'+name,arguments:args});}
  async ready(){await this.rpc('initialize',{protocolVersion:'2025-06-18',capabilities:{elicitation:{}},clientInfo:{name:'reply-regression',version:'1'}});this.send({jsonrpc:'2.0',method:'notifications/initialized'});await this.call('open');}
  calls(){return fs.readFileSync(this.log,'utf8').trim().split('\n').map(JSON.parse);}
}
const data = m => JSON.parse(m.result.content[0].text);
const visibleControl = ({ approvalTarget, ...rest }) => rest;

for(const backend of ['active VM','active computer','lazy VM'])test(backend+' learns refs and exact names from an open observation',async t=>{
 const c=new Client(t,backend!=='active VM');await c.ready();
 const host=backend==='lazy VM'?{host:'vm'}:{};
 await c.call('open',{...host,url:context.url,snapshot:true});
 for(const target of [{ref:link.ref},{name:link.name,role:'link',row:'pioneers'}]){
   const reply=await c.call('action',{...host,action:'click',...target,variant:'unchanged'});
   assert.ok(!reply.result.isError,JSON.stringify(reply));
   assert.equal(c.calls().filter(m=>m.id===reply.id).length,1);
 }
 assert.equal(c.calls().filter(m=>m.params?.name==='cua_alans_way_snapshot').length,0);
});

test('public snapshot text excludes private proof while preserving page state, Unicode and existing MCP metadata',async t=>{
 const c=new Client(t);await c.ready();const reply=await c.call('snapshot');
 const {approvalContext,...expected}=page;expected.elements=[visibleControl(control)];
 assert.deepEqual(data(reply),expected);
 assert.deepEqual(reply.result._meta.custom,{retained:true});
 assert.equal(reply.result._meta.workspace.host,'vps');
 assert.ok(!JSON.stringify(reply).includes(context.documentId),'proof must not be relocated to agent-visible _meta or structuredContent');
});

test('open observations keep public page state while approval proof stays private',async t=>{
 const c=new Client(t);await c.ready();const reply=await c.call('open',{url:context.url,snapshot:true});
 const {approvalContext,...expected}=page;expected.elements=[control,link,actionLink].map(visibleControl);
 assert.deepEqual(data(reply),{...tab,url:'https://fixture.example/before-redirect',observation:expected});
 assert.deepEqual(reply.result._meta.custom,{retained:true});
 assert.ok(!JSON.stringify(reply).includes(context.documentId));
 assert.ok(!JSON.stringify(reply).includes(control.approvalTarget));
});

for(const target of [{ref:'e404'},{name:'Unobserved control'}])test('unseen '+Object.keys(target)[0]+' recovery removes a small element cap',async t=>{
 const c=new Client(t);await c.ready();await c.call('open',{url:context.url,snapshot:true});
 const reply=await c.call('action',{action:'click',...target});
 assert.equal(reply.result.isError,true);assert.match(reply.result.content[0].text,/^snapshot_required:/);
 assert.match(reply.result.content[0].text,/snapshot without a small maxElements limit/i);
 assert.match(reply.result.content[0].text,/300/);assert.match(reply.result.content[0].text,/exact.*name/i);
 assert.equal(c.calls().filter(m=>m.id===reply.id).length,0);
});

test('a small later snapshot keeps observed refs and a complete snapshot restores name binding',async t=>{
 const c=new Client(t);await c.ready();await c.call('open',{url:context.url,snapshot:true});
 await c.call('snapshot',{variant:'open-page',maxElements:1});
 const byRef=await c.call('action',{action:'click',ref:link.ref,variant:'unchanged'});assert.ok(!byRef.result.isError);
 const byName=await c.call('action',{action:'click',name:link.name});assert.match(byName.result.content[0].text,/^snapshot_required:.*maxElements/);
 assert.equal(c.calls().filter(m=>m.id===byName.id).length,0);
 await c.call('snapshot',{variant:'open-page',maxElements:300});
 assert.ok(!(await c.call('action',{action:'click',name:link.name,variant:'unchanged'})).result.isError);
});

for(const variant of ['partial','loading'])test('an open with a '+variant+' observation cannot authorize blind or name-based input',async t=>{
 const c=new Client(t);await c.ready();await c.call('open',{url:context.url,snapshot:true,variant});
 for(const args of [{action:'press',key:'Enter'},{action:'click',name:link.name}]){
   const reply=await c.call('action',args);assert.match(reply.result.content[0].text,/^snapshot_required:/);
   assert.equal(c.calls().filter(m=>m.id===reply.id).length,0);
 }
 assert.ok(!(await c.call('action',{action:'click',ref:link.ref,variant:'unchanged'})).result.isError);
});

for(const variant of ['wrong-tab','read-error','error','large'])test('an open with '+variant+' does not supply usable refs for its tab',async t=>{
 const c=new Client(t);await c.ready();await c.call('open',{url:context.url,snapshot:true,variant});
 const reply=await c.call('action',{action:'click',ref:link.ref});
 assert.match(reply.result.content[0].text,/^snapshot_required:/);
 assert.equal(c.calls().filter(m=>m.id===reply.id).length,0);
});

test('a changed document in an open observation retires refs even when its URL is unchanged and list is partial',async t=>{
 const c=new Client(t);await c.ready();await c.call('open',{url:context.url,snapshot:true});
 await c.call('open',{url:context.url,snapshot:true,variant:'new-document'});
 const reply=await c.call('action',{action:'click',ref:link.ref});
 assert.match(reply.result.content[0].text,/^snapshot_required:/);assert.equal(c.calls().filter(m=>m.id===reply.id).length,0);
});

test('an open observation retains href commit checks, CAPTCHA refusal and tab URL approval binding',async t=>{
 const c=new Client(t);await c.ready();await c.call('open',{url:context.url,snapshot:true,variant:'tab-url'});
 for(const target of [{ref:actionLink.ref},{name:actionLink.name,role:'link'}]){
   const reply=await c.call('action',{action:'click',...target});
   assert.match(reply.result.content[0].text,/^commit_required:.*cart\/delete/);
   assert.equal(c.calls().filter(m=>m.id===reply.id).length,0);
 }
 const id=c.next++;c.send({jsonrpc:'2.0',id,method:'tools/call',params:{name:'cua_alans_way_action',arguments:{action:'click',ref:control.ref,commit:{kind:'purchase',summary:'Inert fixture control'}}}});
 const ask=await c.recv('wsr-commit-1');c.send({jsonrpc:'2.0',id:ask.id,result:{action:'accept'}});await c.recv(id);
 assert.equal(c.calls().find(m=>m.id===id).params.arguments.approval.binding.url,context.url);
 await c.call('open',{url:context.url,snapshot:true,variant:'challenge'});
 const reply=await c.call('action',{action:'click',ref:control.ref});
 assert.match(reply.result.content[0].text,/^challenge_present:/);assert.equal(c.calls().filter(m=>m.id===reply.id).length,0);
});

test('action delta, unchanged and batch envelopes retain effect, continuation, state, errors and user JSON',async t=>{
 const c=new Client(t);await c.ready();await c.call('snapshot');
 const delta=data(await c.call('action',{action:'read',variant:'changed'}));
 assert.deepEqual(delta,{changed:[visibleControl(control)],removed:['e8'],generation:4,tab,effect:{navigated:false,changed:true,text:'new 🌿',value:user},unlisted:9,continuedTab:tab.id,continuedEpoch:7});
 const unchanged=data(await c.call('snapshot',{variant:'unchanged'}));
 assert.deepEqual(unchanged,{unchanged:true,generation:3,tab,loading:false,overlays:[{name:'Banner'}]});
 const batch=data(await c.call('action',{action:'batch',steps:[{action:'read'},{action:'read'}],variant:'batch'}));
 assert.deepEqual(batch,{generation:3,tab,effect:{navigated:false,changed:false,text:''},results:[{ok:true,value:user,elements:[visibleControl(control)]},{ok:false,error:'kept error',approvalContext:'business error detail'}],dispatched:true});
});

test('arbitrary business JSON, eval values, errors, old hosts and unknown proof versions are unchanged',async t=>{
 const c=new Client(t);await c.ready();await c.call('snapshot');
 assert.deepEqual(data(await c.call('status',{variant:'user'})),user);
 assert.deepEqual(data(await c.call('status',{variant:'userPage'})),page,'non-browser observations keep even valid-looking proof keys');
 assert.deepEqual(data(await c.call('snapshot',{variant:'large'})),{...page,text:'x'.repeat(110000)},'uncached large replies retain complete proof');
 assert.deepEqual(data(await c.call('action',{action:'read',variant:'eval'})),{generation:3,tab,effect:{navigated:false,changed:false,text:''},value:user});
 const old=data(await c.call('snapshot',{variant:'old'}));const {approvalContext,...expected}=page;expected.elements=[{ref:'e1',role:'button',name:'Place order'}];assert.deepEqual(old,expected);
 assert.deepEqual(data(await c.call('snapshot',{variant:'unknown'})),{...page,approvalContext:{...context,version:2}});
 const error=await c.call('snapshot',{variant:'error'});assert.equal(error.result.isError,true);assert.deepEqual(data(error),page);assert.deepEqual(error.result._meta.browserRequest,{status:409,code:'ownership_changed'});
});

for(const source of ['snapshot','open'])test('projected '+source+' and unchanged reply still bind one approval and ignore duplicate acceptance',async t=>{
 const c=new Client(t);await c.ready();await c.call(source,source==='open'?{url:context.url,snapshot:true}:{});await c.call('snapshot',{variant:'unchanged'});
 const id=c.next++;c.send({jsonrpc:'2.0',id,method:'tools/call',params:{name:'cua_alans_way_action',arguments:{tabId:tab.id,epoch:7,action:'click',ref:'e1',commit:{kind:'purchase',summary:'Inert fixture control'}}}});
 const ask=await c.recv('wsr-commit-1');assert.equal(ask.method,'elicitation/create');assert.equal(c.calls().filter(m=>m.id===id).length,0);
 const answer={jsonrpc:'2.0',id:ask.id,result:{action:'accept',content:{approve:true}}};c.send(answer);await c.recv(id);c.send(answer);await c.call('status');
 const [sent]=c.calls().filter(m=>m.id===id);assert.equal(c.calls().filter(m=>m.id===id).length,1);
 assert.equal(sent.params.arguments.approval.binding.documentId,context.documentId);
 assert.equal(sent.params.arguments.approval.binding.url,context.url);
 assert.deepEqual(sent.params.arguments.approval.binding.steps[0].targets,[{ref:'e1',token:control.approvalTarget}]);
});

for(const backend of ['active computer','lazy VM'])test(backend+' projects only after caching the original browser reply',async t=>{
 const c=new Client(t,true);await c.ready();const r=await c.call('snapshot',backend==='lazy VM'?{host:'vm'}:{});
 assert.equal(data(r).approvalContext,undefined);assert.equal(data(r).elements[0].approvalTarget,undefined);
 assert.equal(r.result._meta.workspace.host,backend==='lazy VM'?'vm':'mac');
});

for (const computer of [false, true]) test('desktop actions check the expected host before forwarding: '+(computer?'computer online':'computer offline'), async t=>{
 const c=new Client(t,computer,true);await c.ready();
 const action=args=>c.rpc('tools/call',{name:'workspace_computer_action',arguments:{pid:101,action:'key',key:'a',...args}});
 const refused=await action({expect_host:computer?'vm':'computer'});
 assert.equal(refused.result.isError,true);assert.match(refused.result.content[0].text,/^host_changed:/);
 assert.equal(c.calls().filter(m=>m.id===refused.id).length,0,'a stale target never reaches a connector');
 for(const expect_host of [null,1,'mac','box']){
   const reply=await action({expect_host});assert.equal(reply.result.isError,true);
   assert.match(reply.result.content[0].text,/^bad_request:/);
   assert.equal(c.calls().filter(m=>m.id===reply.id).length,0);
 }
 for(const args of [{expect_host:computer?'computer':'vm'},{}]){
   const reply=await action(args);assert.ok(!reply.result.isError);
   assert.equal(c.calls().filter(m=>m.id===reply.id).length,1,'matching and legacy calls still forward once');
 }
 if(computer){
   const refused=await action({host:'vm',expect_host:'computer'});
   assert.equal(refused.result.isError,true);assert.match(refused.result.content[0].text,/^host_changed:/);
   assert.equal(c.calls().filter(m=>m.id===refused.id).length,0,'check the selected host even when the computer is online');
   const reply=await action({host:'vm',expect_host:'vm'});assert.ok(!reply.result.isError);
   assert.equal(reply.result._meta.workspace.host,'vm');
 }
});
