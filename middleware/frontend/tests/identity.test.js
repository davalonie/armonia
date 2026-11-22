import test from 'node:test';
import assert from 'node:assert/strict';
import {getSession,setSession,call} from '../src/lib/api.js';
import {fromQueueTrack} from '../src/lib/homelab.js';

test('a stale tab cannot silently adopt another tabs cookie identity',async()=>{
  const values=new Map();
  globalThis.localStorage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
  setSession({username:'alice',userId:'alice-id'});
  localStorage.setItem('armonia.session',JSON.stringify({userId:'bob-id'}));
  globalThis.fetch=async(path,opts)=>{
    assert.equal(opts.headers['X-Music-Owner'],'alice-id');
    return {ok:false,status:409,text:async()=> 'account changed'};
  };
  assert.equal(getSession().userId,'alice-id');
  await assert.rejects(call('/api/mixed-playlists'),err=>err.status===409);
});
test('Navidrome recording and artist identifiers survive conversion',()=>{
  const id='11111111-1111-4111-8111-111111111111';
  const t=fromQueueTrack({id:'song',title:'Song',artist:'Artist',duration:200,
    musicBrainzId:id,artists:[{musicBrainzId:id},{musicBrainzId:'bad'}],isrc:['USAAA2600001']});
  assert.equal(t.recording_mbid,id);assert.deepEqual(t.artist_mbids,[id]);
  assert.equal(t.isrc,'USAAA2600001');
});
test('a blackholed session check times out instead of leaving authentication busy indefinitely',async t=>{
  t.mock.timers.enable({apis:['setTimeout']});
  globalThis.fetch=async(path,opts)=>new Promise((resolve,reject)=>opts.signal.addEventListener('abort',()=>reject(new Error('aborted')),{once:true}));
  const {me}=await import('../src/lib/api.js');
  const result=assert.rejects(me(),/aborted/);
  t.mock.timers.tick(30000);
  await result;
});
