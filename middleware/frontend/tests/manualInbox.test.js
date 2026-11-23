import test from 'node:test';
import assert from 'node:assert/strict';
import {setSession} from '../src/lib/api.js';
import {MAX_MANUAL_AUDIO_BYTES,validateManualAudio,manualInboxError,pendingAudioLabel,loadManualInbox,uploadManualAudio,refreshManualPending,deleteManualPending} from '../src/lib/manualInbox.js';

const storage=new Map();
globalThis.localStorage={getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)};
const pending={id:'fixture/id',revision:7,status:'pending',track:{title:'Fixture',artist:'Synthetic'}};
const capture=response=>{
  const requests=[];
  globalThis.fetch=async(path,options)=>{requests.push({path,options});return {ok:true,text:async()=>JSON.stringify(response)};};
  setSession({username:'fixture',userId:'alice'});
  return requests;
};

test('raw MP3 upload preserves session guards and revision without copying or encoding the audio',async()=>{
  const requests=capture({...pending,status:'saved',songId:null});
  const audio=new Blob([new Uint8Array([1,2,3])],{type:'audio/mpeg'});
  Object.defineProperty(audio,'name',{value:'fixture.MP3'});
  const controller=new AbortController();
  const result=await uploadManualAudio(pending,audio,{signal:controller.signal});
  assert.equal(requests.length,1);
  const {path,options}=requests[0];
  assert.equal(path,'/api/manual-inbox/fixture%2Fid/upload');
  assert.equal(options.method,'POST');
  assert.equal(options.body,audio);
  assert.equal(options.headers['Content-Type'],'audio/mpeg');
  assert.equal(options.headers['X-Item-Revision'],'7');
  assert.equal(options.headers['X-Music-Owner'],'alice');
  assert.equal(options.headers['X-Music-Client'],'web');
  assert.equal(options.credentials,'same-origin');
  assert.equal(options.signal,controller.signal);
  assert.equal(result.status,'saved');
});

test('invalid or oversized files are rejected before any request; the exact limit is allowed',()=>{
  const requests=capture({});
  for(const file of [null,{name:'fixture.wav',size:8},{name:'fixture.mp3',size:0},{name:'fixture.mp3',size:MAX_MANUAL_AUDIO_BYTES+1}]) {
    assert.throws(()=>uploadManualAudio(pending,file));
  }
  assert.equal(requests.length,0);
  assert.doesNotThrow(()=>validateManualAudio({name:'fixture.mp3',size:MAX_MANUAL_AUDIO_BYTES}));
});

test('index refresh and inbox removal send only the revision, never audio or playlist mutations',async()=>{
  const requests=capture({items:[]});
  await loadManualInbox();await refreshManualPending(pending);await deleteManualPending(pending);
  assert.deepEqual(requests.map(req=>[req.path,req.options.method]),[
    ['/api/manual-inbox',undefined],['/api/manual-inbox/fixture%2Fid/refresh','POST'],['/api/manual-inbox/fixture%2Fid','DELETE'],
  ]);
  for(const req of requests.slice(1)) assert.deepEqual(JSON.parse(req.options.body),{revision:7});
});

test('saved audio waiting for indexing is distinct from a pending upload',()=>{
  assert.match(pendingAudioLabel(pending),/aportar un MP3/);
  assert.match(pendingAudioLabel({...pending,status:'saved',songId:null,error:'index_pending'}),/Audio guardado/);
  assert.equal(pendingAudioLabel({...pending,status:'saved',songId:'local-1'}),'Guardada en tu biblioteca');
});

test('HTTP and network failures have safe actionable messages without exposing upstream bodies',()=>{
  for(const status of [401,403,404,409,413,415,422,429,500,507]) {
    const text=manualInboxError({status,detail:'token=secret /srv/private/photo http://upstream/?password=secret',message:'secret'});
    assert.doesNotMatch(text,/secret|private|upstream/);
    assert(text.length>10);
  }
  assert.match(manualInboxError({name:'AbortError'}),/comprobar si el archivo se guardo/);
  assert.match(manualInboxError({status:409}),/Actualiza/);
});
