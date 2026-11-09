#!/usr/bin/env node
/** Real 0.2.2 services; shell tools are memory-only, never device commands. */
import assert from 'node:assert/strict';
import Module from 'node:module';
import {readFile, mkdtemp, mkdir, writeFile, rm} from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const install=path.resolve(process.argv[2]||'');
const build=path.resolve('app/build');
assert.ok(install.startsWith(build+path.sep),'Use an isolated runtime under app/build');
const modules=path.join(install,'node_modules');
const load=name=>import(pathToFileURL(path.join(modules,'@deepseek-ai',name,'lib/index.js')));
for(const name of ['dsh','dsh-tools','dsh-tool-executor-native','dsh-tool-executor-ptc','dsh-storage-json'])
 assert.equal(JSON.parse(await readFile(path.join(modules,'@deepseek-ai',name,'package.json'))).version,'0.2.2-rc.1');
const [{Context},{ToolsService},{NativeToolExecutor},{PtcExecutor},{ToolExecutionPipeline},{JsonStorageBackend}]=await Promise.all([
 load('cordis'),load('dsh-tools'),load('dsh-tool-executor-native'),load('dsh-tool-executor-ptc'),
 import(pathToFileURL(path.join(modules,'@deepseek-ai/dsh-tools/lib/pipeline.js'))),load('dsh-storage-json')]);
const base={schema:1,available:true,globalAllow:false,revision:1,installationId:'11111111-1111-4111-8111-111111111111',bridgeRunId:'22222222-2222-4222-8222-222222222222',webGeneration:1,runtimeInstanceId:'33333333-3333-4333-8333-333333333333:1'};
let active;
const originalLoad=Module._load;
Module._load=function(request,...args){
 if(request!=='/run/dsha-launcher/native-consent.cjs')return originalLoad.call(this,request,...args);
 if(active.missing)throw Error('fixture SDK unavailable');
 return {readConnection:()=>({applicationId:'io.github.foreveryf.dsha',generation:1}),bridgeFetch:async()=>({ok:true,json:async()=>({result:JSON.stringify(active.consent)})})};
};
const passed=[];
async function fixture(opts={}){
 const ctx=new Context();
 const f={ctx,consent:{...base,...opts.consent},bodies:0,asks:0,missing:opts.missing};active=f;
 ctx.provide('systemPrompt',{tools(){},section(){return ()=>{};},getSectionOrder(){return 1;}});
 ctx.provide('workingDirectory',{get:()=>'/tmp',ensure:async()=>'/tmp'});
 ctx.provide('shellEnv',{collect:()=>({})});
 ctx.provide('approval',{effectivePolicy:()=>opts.never?'never':'ask',request:async()=>{f.asks++;return opts.answer??'allowed-once';}});
 ctx.provide('ptcRuntime',{language:'typescript',resolve:v=>v,release(){},async run(request){try{return {logs:[],value:await request.bindings[0].functions.bash({command:'rm /tmp/dsha-test-never-executed'})};}catch(error){return {logs:[],error:{kind:'runtime',message:error.message}};}}});
 const tools=new ToolsService(ctx);f.tools=tools;
 f.executor=opts.ptc?new PtcExecutor(ctx):new NativeToolExecutor(ctx);tools.setExecutor(f.executor);
 f.definition={name:'bash',description:'Memory-only counter; NEVER executes a command',parameters:{command:{type:'string',required:true}},output:{schema:{type:'object'},render:()=>[{type:'text',text:'counter'}]},execute(){f.bodies++;return {count:f.bodies};}};
 tools.register(f.definition);
 f.agent={ctx,session:{id:'fixture-session',header:{cwd:'/tmp'},append(){}}};
 f.controller=new AbortController();
 f.input={name:'bash',callId:'fixture-call',arguments:{command:'rm /tmp/dsha-test-never-executed'},agent:f.agent,signal:f.controller.signal};
 f.pipeline=new ToolExecutionPipeline(ctx);
 f.batch=()=>tools.execute({calls:[{type:'tool-call',name:opts.ptc?'run_code':'bash',id:'fixture-call',arguments:JSON.stringify(opts.ptc?{code:'fixture calls memory-only binding',description:'Exercise guarded nested call'}:f.input.arguments)}],agent:f.agent,signal:f.controller.signal});
 return f;
}
async function test(name,opts,action){const f=await fixture(opts);try{await action(f);passed.push(name);console.log('PASS '+name);}finally{await f.ctx.fiber.dispose();}}
async function allowed(f){const r=await f.batch();assert.equal(r.results[0].result.isError,false);assert.equal(f.bodies,1);assert.equal(f.asks,1);}
async function denied(f){const r=await f.batch();assert.equal(r.results[0].result.isError,true);assert.equal(f.bodies,0);}
try{
 for(const ptc of [false,true]){
  const p=ptc?'ptc-nested':'native';
  await test(p+'-one-time-approval',{ptc},allowed);
  await test(p+'-user-rejection',{ptc,answer:'rejected'},async f=>{await denied(f);assert.equal(f.asks,1);});
  await test(p+'-never-is-not-consent',{ptc,never:true},async f=>{await denied(f);assert.equal(f.asks,0);});
  await test(p+'-missing-native-sdk',{ptc,missing:true},async f=>{await denied(f);assert.equal(f.asks,0);});
  await test(p+'-invalid-native-proof',{ptc,consent:{runtimeInstanceId:'mismatched'}},denied);
 }
 for(const [name,mutate] of [
  ['changed-consent-revision',f=>f.consent.revision++],
  ['changed-native-generation',f=>{f.consent.webGeneration=2;f.consent.runtimeInstanceId='33333333-3333-4333-8333-333333333333:2';}],
  ['changed-workdir',f=>f.agent.session.header.cwd='/changed'],
  ['changed-tool-body',f=>{f.definition.execute=()=>{f.bodies++;return {};};}],
  ['caller-cancellation',f=>f.controller.abort('fixture')]
 ])await test(name,{},async f=>{const p=await f.pipeline.prepare(f.input);assert.equal(p.kind,'dispatch');mutate(f);const r=await f.pipeline.dispatch(p.exec);assert.equal(r.result.isError,true);assert.equal(f.bodies,0);});
 await test('immutable-execution-and-no-replay',{},async f=>{const p=await f.pipeline.prepare(f.input);assert.equal(p.kind,'dispatch');assert.throws(()=>{p.exec.name='other';},TypeError);const r=await f.pipeline.dispatch(p.exec);assert.equal(r.result.isError,false);assert.equal(f.bodies,1);const again=await f.pipeline.dispatch(p.exec);assert.equal(again.result.isError,true);assert.equal(f.bodies,1);});
}finally{Module._load=originalLoad;}
const root=await mkdtemp(path.join(build,'storage-022-'));
const descriptor=name=>({name,version:2,compatibleVersions:[1],tables:['items'],hasGlobal:false,layout:'per-record'});
let backend=new JsonStorageBackend(root);
try{
 const d=descriptor('fork_storage');
 let unit=await backend.kv.open(d);
 await unit.putRecord('items','one',{value:1});await unit.putRecord('items','two',{value:2});await unit.close();
 unit=await backend.kv.open(d);assert.deepEqual((await unit.loadAll()).tables.items,{one:{value:1},two:{value:2}});
 await unit.deleteRecords('items',['one','two','one']);await unit.close();
 unit=await backend.kv.open(d);assert.deepEqual((await unit.loadAll()).tables.items,{});await unit.close();passed.push('storage-put-reopen-atomic-multi-delete');
 const compatible=descriptor('fork_compatible');await mkdir(path.join(root,compatible.name,'items'),{recursive:true});
 await writeFile(path.join(root,compatible.name,'items/old.json'),JSON.stringify({version:1,record:{value:'old'}}));
 unit=await backend.kv.open(compatible);assert.deepEqual((await unit.loadAll()).tables.items.old,{value:'old'});await unit.putRecord('items','old',{value:'updated'});await unit.close();
 assert.equal(JSON.parse(await readFile(path.join(root,compatible.name,'items/old.json'))).version,2);passed.push('storage-explicit-compatible-reader-current-writer');
 const empty=descriptor('fork_empty');await mkdir(path.join(root,empty.name,'items'),{recursive:true});
 await writeFile(path.join(root,empty.name+'.json'),JSON.stringify({unit:{name:empty.name,version:2},global:null,tables:{items:{legacy:{bad:true}}}}));
 unit=await backend.kv.open(empty);assert.deepEqual((await unit.loadAll()).tables.items,{});await unit.close();passed.push('storage-empty-materialized-table-blocks-legacy-resurrection');
 await backend.close();backend=new JsonStorageBackend(root);unit=await backend.kv.open(compatible);assert.deepEqual((await unit.loadAll()).tables.items.old,{value:'updated'});await unit.close();passed.push('storage-fresh-backend-reopens-current-record');
}finally{await backend.close();await rm(root,{recursive:true,force:true});}
console.log(JSON.stringify({status:'PASS',version:'0.2.2-rc.1',tests:passed.length,cases:passed,scope:'Actual native and PTC executor/pipeline, with memory-only tools and fixture native-consent SDK; real JSON storage. No shell, device, paid API, browser or cross-version DSHA backup validation.'}));
