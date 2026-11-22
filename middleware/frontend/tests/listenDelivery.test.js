import test from 'node:test';
import assert from 'node:assert/strict';
import {setSession} from '../src/lib/api.js';
import {retainListen,flushListens,rejectedListens} from '../src/lib/listenDelivery.js';
function storage(){
 const values=new Map();
 globalThis.localStorage={getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k),key:i=>[...values.keys()][i],get length(){return values.size;}};
 setSession({userId:'alice'});return values;
}
const response=(status,detail)=>({ok:status<400,status,text:async()=>JSON.stringify({detail})});
test('corrupt offline listens are preserved and never replaced by a new event', async()=>{
 const values=storage();values.set('music:listens:alice','incomplete JSON');
 assert.equal(retainListen('alice',{id:'new'}),false);await flushListens();
 assert.equal(values.get('music:listens:alice'),'incomplete JSON');
});
test('legacy queue migrates without changing payload and another tab appending during delivery is preserved',async()=>{
 const values=storage();values.set('music:listens:alice',JSON.stringify([{id:'first',started_at:100}]));
 globalThis.fetch=async(path,opts)=>{
  assert.deepEqual(JSON.parse(opts.body),{id:'first',started_at:100});
  values.set('music:listens:alice:event:second',JSON.stringify({id:'second'}));
  return response(202);
 };
 await flushListens();assert.equal(values.has('music:listens:alice'),false);assert.equal(values.has('music:listens:alice:event:first'),false);
 assert.deepEqual(JSON.parse(values.get('music:listens:alice:event:second')),{id:'second'});
});
test('account mismatch and temporary upstream failures retain the pending event',async()=>{
 const values=storage();values.set('music:listens:alice:event:one',JSON.stringify({id:'one'}));
 for(const [code,detail] of [[409,'account changed; reload before retrying'],[401,'expired'],[502,'unavailable']]){
  globalThis.fetch=async()=>response(code,detail);await flushListens();
  assert.equal(values.has('music:listens:alice:event:one'),true);assert.equal(rejectedListens(),0);
 }
});
test('only invalid payloads or explicit event conflicts are quarantined without blocking newer events',async()=>{
 const values=storage();values.set('music:listens:alice:event:bad',JSON.stringify({id:'bad'}));values.set('music:listens:alice:event:good',JSON.stringify({id:'good'}));
 globalThis.fetch=async(path,opts)=>JSON.parse(opts.body).id==='bad'?response(409,'event id already used with different content'):response(202);
 await flushListens();assert.equal(rejectedListens(),1);assert.equal(values.has('music:listens:alice:event:good'),false);
});
test('storage failure during migration leaves original array intact',async()=>{
 const values=storage();const raw=JSON.stringify([{id:'one'}]);values.set('music:listens:alice',raw);
 localStorage.setItem=()=>{throw new Error('quota');};await flushListens();assert.equal(values.get('music:listens:alice'),raw);
});
test('an interleaved other-tab retention survives a simultaneous local write',async()=>{
 const values=storage();const read=localStorage.getItem;let interleave=true,finish;
 localStorage.getItem=key=>{const value=read(key);if(key==='music:listens:alice'&&interleave){interleave=false;values.set('music:listens:alice:event:other',JSON.stringify({id:'other'}));}return value;};
 globalThis.fetch=()=>new Promise(resolve=>{finish=resolve;});
 assert.equal(retainListen('alice',{id:'mine'}),true);
 assert.equal(values.has('music:listens:alice:event:other'),true);assert.equal(values.has('music:listens:alice:event:mine'),true);
 globalThis.fetch=async()=>response(202);finish(response(202));await new Promise(resolve=>setImmediate(resolve));
});
