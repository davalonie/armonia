import test from 'node:test';
import assert from 'node:assert/strict';
import {createContinuation,withoutKnown} from '../src/lib/continuation.js';

const item=n=>({track:{source:'youtube',source_id:'v'+n}});
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};

test('one request per context, handed out once',async()=>{
  let calls=0;const c=createContinuation(async()=>{calls++;return {enabled:true,items:[item(1),item(2)]};});
  c.prepare({});c.prepare({});
  assert.equal((await c.take({})).length,2);
  assert.equal(calls,1);
  await c.take({});assert.equal(calls,2); // The next end of queue asks for a fresh batch.
});

test('a batch that arrives after the queue changed is dropped',async()=>{
  const gate=deferred();const c=createContinuation(()=>gate.promise);
  const taking=c.take({});
  c.invalidate(); // The user started another playlist meanwhile.
  gate.resolve({enabled:true,items:[item(1)]});
  assert.deepEqual(await taking,[]);
});

test('duplicate end events share one batch and only one receives it',async()=>{
  const gate=deferred();let calls=0;const c=createContinuation(()=>{calls++;return gate.promise;});
  const a=c.take({}),b=c.take({});
  gate.resolve({enabled:true,items:[item(1)]});
  const got=[await a,await b];
  assert.equal(calls,1);
  assert.deepEqual(got.map(g=>g.length).sort(),[0,1]);
});

test('option off on the server, revoked session or network failure end cleanly',async()=>{
  assert.deepEqual(await createContinuation(async()=>({enabled:false,items:[item(1)]})).take({}),[]);
  assert.deepEqual(await createContinuation(async()=>{throw new Error('401');}).take({}),[]);
  assert.deepEqual(await createContinuation(()=>{throw new Error('sync');}).take({}),[]);
});

test('known songs are filtered and a batch never repeats itself',()=>{
  assert.deepEqual(withoutKnown([item(1),item(2),item(2),item(3)],['youtube:v1']),[item(2),item(3)]);
});
