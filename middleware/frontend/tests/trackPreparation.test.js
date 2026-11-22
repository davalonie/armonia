import test from 'node:test';
import assert from 'node:assert/strict';
import {createTrackPreparation} from '../src/lib/trackPreparation.js';

const flush=()=>new Promise(resolve=>setImmediate(resolve));
function setup(request){
  let time=0,owner='alice',id=0;
  const timers=new Map();
  const prep=createTrackPreparation(request,{
    now:()=>time,ownerNow:()=>owner,
    schedule:(fn,delay)=>{timers.set(++id,{fn,at:time+delay});return id;},
    unschedule:id=>timers.delete(id),
  });
  return {prep,timers,setOwner:value=>owner=value,
    async tick(ms){time+=ms;for(const [id,t] of [...timers])if(t.at<=time){timers.delete(id);t.fn();}await flush();},
  };
}
test('skipped and transient failure retry, ready deduplicates until expiry',async()=>{
  let calls=0;
  const lab=setup(async()=>{calls++;if(calls===1)return {state:'skipped'};if(calls===2)throw new Error('offline');return {state:'ready'};});
  lab.prep.prepare('alice','first');await flush();assert.equal(calls,1);
  lab.prep.prepare('alice','first');await lab.tick(1000);assert.equal(calls,2);
  await lab.tick(3000);assert.equal(calls,3);assert.equal(lab.timers.size,0);
  lab.prep.prepare('alice','first');await flush();assert.equal(calls,3);
  await lab.tick(60000);lab.prep.prepare('alice','first');await flush();assert.equal(calls,4);
});
test('retry budget is finite and cancellation suppresses queued retries',async()=>{
  let calls=0;const lab=setup(async()=>{calls++;return {state:'skipped'};});
  lab.prep.prepare('alice','first');await flush();await lab.tick(1000);await lab.tick(3000);await lab.tick(90000);
  assert.equal(calls,3);assert.equal(lab.timers.size,0);
  lab.prep.prepare('alice','first');await flush();lab.prep.cancel();await lab.tick(90000);assert.equal(calls,4);
});
test('new next song aborts old request and its delayed answer cannot alter new target',async()=>{
  const calls=[];
  const lab=setup((id,signal)=>new Promise(resolve=>calls.push({id,signal,resolve})));
  lab.prep.prepare('alice','first');lab.prep.prepare('alice','second');
  assert.equal(calls[0].signal.aborted,true);
  calls[0].resolve({state:'ready'});await flush();
  lab.prep.prepare('alice','second');assert.equal(calls.length,2);
  calls[1].resolve({state:'preparing'});await flush();assert.equal(lab.timers.size,0);
  lab.prep.prepare('alice','first');assert.equal(calls.length,3);lab.prep.reset();calls[2].resolve({state:'ready'});await flush();
});
test('account change cannot seed another account cache and authorization failures do not retry',async()=>{
  let resolve,calls=0;
  const lab=setup(()=>{calls++;return calls===1?new Promise(done=>resolve=done):Promise.reject(Object.assign(new Error('forbidden'),{status:403}));});
  lab.prep.prepare('alice','first');lab.setOwner('bob');resolve({state:'ready'});await flush();
  assert.equal(lab.timers.size,0);
  lab.prep.prepare('bob','first');await flush();await lab.tick(90000);assert.equal(calls,2);
});
test('reset clears cached successes between sessions',async()=>{
  let calls=0;const lab=setup(async()=>{calls++;return {state:'ready'};});
  lab.prep.prepare('alice','first');await flush();lab.prep.reset();
  lab.prep.prepare('alice','first');await flush();assert.equal(calls,2);
});
