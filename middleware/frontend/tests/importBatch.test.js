import test from 'node:test';
import assert from 'node:assert/strict';
import {setSession} from '../src/lib/api.js';
import {validateArchive,batchError,noteLabel,importable,playlistProgress,pauseReason,proposeFromArchive,startBatch,MAX_ZIP_BYTES} from '../src/lib/importBatch.js';

const storage=new Map();
globalThis.localStorage={getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};

test('only a ZIP within the limit is sent, as it is',async()=>{
  assert.throws(()=>validateArchive({name:'lista.csv',size:10}),/ZIP/);
  assert.throws(()=>validateArchive({name:'todo.zip',size:0}),/vacio/);
  assert.throws(()=>validateArchive({name:'todo.zip',size:MAX_ZIP_BYTES+1}),/8 MiB/);
  const requests=[];
  globalThis.fetch=async(path,options)=>{requests.push({path,options});return {ok:true,text:async()=>'{"id":"b"}'};};
  setSession({username:'fixture',userId:'alice'});
  const file={name:'spotify_playlists.zip',size:100};
  await proposeFromArchive(file);
  assert.equal(requests[0].path,'/api/import-batch/zip');
  assert.equal(requests[0].options.body,file);
  assert.equal(requests[0].options.headers['Content-Type'],'application/zip');
  await startBatch('b/1',[0,2],{2:'Nuevo'});
  assert.equal(requests[1].path,'/api/import-batch/b%2F1/start');
  assert.deepEqual(JSON.parse(requests[1].options.body),{selected:[0,2],names:{2:'Nuevo'}});
});

test('rows say what happened to each playlist without inventing success',()=>{
  assert.equal(importable({total:3,note:null}),true);
  assert.equal(importable({total:3,note:'resource_limit'}),true);
  assert.equal(importable({total:0,note:'empty'}),false);
  assert.equal(importable({total:9,note:'too_large'}),false);
  assert.equal(noteLabel('unreadable'),'Vacia o ilegible');
  assert.equal(noteLabel(null),'');
  assert.deepEqual(playlistProgress({state:'waiting'}),{label:'En espera',tone:'muted'});
  assert.deepEqual(playlistProgress({state:'failed'}),{label:'No se pudo iniciar',tone:'error'});
  assert.deepEqual(playlistProgress({state:'running',import:{status:'running',current:4,total:9}}),{label:'Importando 4/9',tone:'active'});
  assert.deepEqual(playlistProgress({state:'started',import:{status:'done',review:0}}),{label:'Importada',tone:'done'});
  assert.deepEqual(playlistProgress({state:'started',import:{status:'done',review:3}}),{label:'Importada · 3 por revisar',tone:'review'});
  assert.equal(playlistProgress({state:'started',import:{status:'paused',review:0}}).tone,'review');
  assert.equal(playlistProgress({state:'started',import:null}).label,'Historial eliminado');
  assert.match(pauseReason('busy'),/otra importacion/);
  assert.match(pauseReason('interrupted'),/reinicio/);
  assert.equal(batchError({status:413}),'El archivo es demasiado grande o contiene demasiadas playlists.');
});
