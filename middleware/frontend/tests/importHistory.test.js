import test from 'node:test';
import assert from 'node:assert/strict';
import {importHistoryGroups,importWorkState} from '../src/lib/importHistory.js';

const completed=(changes={})=>({importId:'done',name:'Synthetic list',status:'done',total:474,current:474,
  ready:464,skipped:10,legacySkipped:0,needsReview:0,errors:0,failed:0,indexing:0,queued:0,inProgress:0,
  unavailable:0,sourceInfo:{source_complete:true},...changes});

test('474 processed positions with one stored file awaiting indexing remain pending',()=>{
  const job=completed({ready:463,indexing:1,downloaded:400,existing:64});
  assert.deepEqual(importWorkState(job),{pending:true,label:'1 esperando la biblioteca',onlyIndexing:true});
  assert.equal(importHistoryGroups([job]).completed.length,0);
});

test('done is not completion for review, failed, queued or unavailable positions',()=>{
  for(const changes of [{needsReview:1},{errors:1},{queued:1},{inProgress:1},{unavailable:1},{error:'playlist_missing'},{status:'paused'},{status:'error'}]) {
    assert.equal(importWorkState(completed(changes)).pending,true,JSON.stringify(changes));
  }
  assert.equal(importWorkState(completed({status:'running'})).pending,true);
});

test('confirmed manual omissions do not prevent completion; legacy or unknown omissions do',()=>{
  assert.equal(importWorkState(completed()).pending,false);
  assert.equal(importWorkState(completed({legacySkipped:1})).pending,true);
  const legacy=completed();delete legacy.legacySkipped;
  assert.equal(importWorkState(legacy).pending,true);
  const items=[{state:'ready'},{state:'skipped',manualPending:true}];
  assert.equal(importWorkState(completed({total:2,items})).pending,false);
  assert.equal(importWorkState(completed({total:2,items:[{state:'ready'},{state:'skipped'}]})).pending,true);
});

test('partial source coverage and incomplete old summaries are not silently archived',()=>{
  assert.equal(importWorkState(completed({sourceInfo:{source_complete:false,retrieved:99}})).pending,true);
  assert.equal(importWorkState(completed({notRetrieved:7})).pending,true);
  assert.equal(importWorkState({importId:'old',status:'done',current:99,total:99}).pending,true);
  assert.equal(importWorkState(completed({ready:462})).pending,true);
});

test('new authoritative summary flags work without fetching every import detail',()=>{
  assert.equal(importWorkState({importId:'new',status:'done',hasPendingWork:false}).pending,false);
  assert.equal(importWorkState({importId:'new',status:'done',hasPendingWork:true}).pending,true);
});

test('polling replaces stale summary and removes only completed jobs from pending selector',()=>{
  const history=[completed(),completed({importId:'second',indexing:1,ready:463}),completed({importId:'third',needsReview:1,ready:463})];
  const snapshot=JSON.stringify(history);
  const first=importHistoryGroups(history);
  assert.deepEqual(first.pending.map(job=>job.importId),['second','third']);
  assert.deepEqual(first.completed.map(job=>job.importId),['done']);
  const polled=completed({importId:'second',hasPendingWork:false});
  const next=importHistoryGroups(history,polled);
  assert.deepEqual(next.pending.map(job=>job.importId),['third']);
  assert.deepEqual(next.completed.map(job=>job.importId),['done','second']);
  assert.equal(JSON.stringify(history),snapshot);
  assert.equal(importHistoryGroups([],completed({importId:'new',status:'running'})).pending.length,1);
});

test('library-only recovery label is not used when source, other errors or queued work remains',()=>{
  for(const changes of [{queued:1},{unavailable:1},{legacySkipped:1},{needsReview:1},{errors:1},{sourceInfo:{source_complete:false}},{error:'service_unavailable'},
    {ready:462},{items:[{state:'indexing'}]},{total:undefined}]) {
    assert.notEqual(importWorkState(completed({indexing:1,ready:463,...changes})).onlyIndexing,true);
  }
});

test('a stopped stale active detail cannot override a newer completed summary from another device',()=>{
  const active=completed({importId:'remote',revision:11,hasPendingWork:true,indexing:1,ready:463});
  const fresh=completed({importId:'remote',revision:12,hasPendingWork:false});
  const groups=importHistoryGroups([fresh],active);
  assert.deepEqual(groups.pending,[]);
  assert.deepEqual(groups.completed,[fresh]);
  // A later in-flight poll still takes precedence over an older list request.
  const polled={...active,revision:13};
  assert.deepEqual(importHistoryGroups([fresh],polled).pending,[polled]);
  assert.deepEqual(importHistoryGroups([fresh],{...active,revision:undefined}).completed,[fresh]);
});
