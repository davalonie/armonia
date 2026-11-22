import test from 'node:test';
import assert from 'node:assert/strict';
import {get} from 'svelte/store';
import {setSession} from '../src/lib/api.js';
import * as player from '../src/lib/stores/playerStore.js';

const values=new Map();
globalThis.localStorage={getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k),key:i=>[...values.keys()][i],get length(){return values.size;}};
globalThis.window={addEventListener(){}};
class Audio extends EventTarget {
  currentTime=0;duration=200;paused=true;ended=false;src='';
  play(){this.paused=false;return Promise.resolve();}
  pause(){this.paused=true;this.dispatchEvent(new Event('pause'));}
  removeAttribute(){this.src='';}
  load(){this.released=true;}
}
const song=id=>({id,title:id,artist:'Fixture',duration:200});
function setup() {
  globalThis.fetch=async()=>({ok:true,text:async()=>JSON.stringify({'subsonic-response':{status:'ok'}})});
  values.clear();setSession({userId:'alice'});
  player.queue.set([]);player.currentIndex.set(-1);player.shuffleOn.set(false);player.repeatMode.set('off');
  const audio=new Audio();player.initAudio(audio);return audio;
}
test('reordering across the playing entry preserves audio, metadata and active index',()=>{
 const audio=setup();player.playQueue(['a','b','c','d'].map(song),1);
 player.reorderQueue(0,4);
 assert.equal(get(player.currentTrack).id,'b');assert.equal(audio.src,'/api/stream/b');assert.equal(get(player.currentIndex),0);
 player.reorderQueue(0,4);
 assert.equal(get(player.currentTrack).id,'b');assert.equal(get(player.currentIndex),3);
});
test('shuffle queue deletion/addition/reorder never produces stale indices or skips the added entry',()=>{
 setup();player.playQueue(['a','b','c','d'].map(song));player.toggleShuffle();
 player.removeFromQueue(1);player.addToQueue(song('e'));player.reorderQueue(2,1);
 const played=[get(player.currentTrack).id];
 for(let i=0;i<3;i++){player.next();assert.ok(get(player.currentTrack));played.push(get(player.currentTrack).id);}
 assert.equal(new Set(played).size,4);assert.deepEqual([...played].sort(),['a','c','d','e']);
});
test('late favourite response updates its original track, not a newly playing track',async()=>{
 setup();player.playQueue(['a','b'].map(song));
 let finish;globalThis.fetch=async(path)=>path.includes('/star?')?await new Promise(resolve=>finish=resolve):({ok:true,text:async()=>JSON.stringify({'subsonic-response':{status:'ok'}})});
 const pending=player.toggleLike();player.next();
 finish({ok:true,text:async()=>JSON.stringify({'subsonic-response':{status:'ok'}})});await pending;
 assert.equal(get(player.currentTrack).id,'b');assert.equal(get(player.currentTrack).starred,undefined);assert.ok(get(player.queue)[0].starred);
});
test('a delayed menu favourite action keeps its captured song after playback advances',async()=>{
 setup();const a=song('a');player.playQueue([a,song('b')]);player.next();
 await player.toggleTrackLike(a);
 assert.equal(get(player.currentTrack).starred,undefined);assert.ok(get(player.queue)[0].starred);
});
test('queue playback takes a snapshot and closing releases the HTTP source',()=>{
 const audio=setup();const tracks=['a','b'].map(song);player.playQueue(tracks);tracks.pop();
 assert.equal(get(player.queue).length,2);player.closePlayer();assert.equal(audio.src,'');assert.equal(audio.released,true);
});
test('a transient local quota failure retries the same listen instead of marking it permanently submitted',async()=>{
 const audio=setup();let now=0;const originalNow=performance.now;Object.defineProperty(performance,'now',{value:()=>now,configurable:true});
 let blocked=true;const ids=[];
 const write=localStorage.setItem;
 localStorage.setItem=(key,value)=>{if(key.includes(':event:')){ids.push(JSON.parse(value).id);if(blocked)throw new Error('quota');}write(key,value);};
 try {
  player.playQueue([song('a')]);
  for(let i=0;i<=100;i++){now=i*1000;audio.currentTime=i;audio.dispatchEvent(new Event('timeupdate'));}
  assert.equal(ids.length,1);
  blocked=false;now=101000;audio.currentTime=101;audio.dispatchEvent(new Event('timeupdate'));
  assert.equal(ids.length,2);assert.equal(ids[0],ids[1]);
  await new Promise(resolve=>setImmediate(resolve));
 } finally {Object.defineProperty(performance,'now',{value:originalNow,configurable:true});}
});
test('a single preview resets an earlier shuffle traversal',()=>{
 setup();player.playQueue(['a','b','c'].map(song));player.toggleShuffle();
 player.playPreviewTrack({...song('external'),_previewUrl:'/api/external/fixture'});player.next();
 assert.equal(get(player.currentIndex),0);assert.equal(get(player.currentTrack).id,'external');
});
test('unavailable browser storage cannot prevent closing the player',()=>{
 const audio=setup();player.playQueue([song('a')]);localStorage.removeItem=()=>{throw new Error('storage unavailable');};
 assert.doesNotThrow(()=>player.closePlayer());assert.equal(get(player.currentTrack),null);assert.equal(audio.src,'');
});

test('audition retains queue and position, pauses at ten seconds, and never records listens',()=>{
 const audio=setup();player.playQueue(['a','b','a'].map(song),1);audio.currentTime=37;
 const original=[...get(player.queue)];
 player.audition({...song('candidate'),_previewUrl:'/api/preview/abcdefghijk'});
 assert.deepEqual(get(player.queue),original);
 audio.dispatchEvent(new Event('loadedmetadata'));
 assert.equal(audio.currentTime,95);
 audio.dispatchEvent(new Event('play'));
 for(let i=95;i<=200;i++){audio.currentTime=i;audio.dispatchEvent(new Event('timeupdate'));}
 assert.equal(audio.paused,true);
 assert.equal([...values.keys()].some(k=>k.includes(':event:')),false);
 player.stopPreview();audio.dispatchEvent(new Event('loadedmetadata'));
 assert.equal(audio.currentTime,37);assert.equal(get(player.currentTrack).id,'b');assert.equal(audio.paused,true);
 player.closePlayer();
});
test('cancelling a loading audition prevents delayed metadata from starting it',()=>{
 const audio=setup();player.playQueue([song('a')]);player.audition({...song('x'),_previewUrl:'/api/preview/abcdefghijk'});
 player.pausePreview();audio.dispatchEvent(new Event('loadedmetadata'));
 assert.equal(audio.paused,true);assert.equal(get(player.previewState).status,'paused');player.stopPreview();player.closePlayer();
});
test('rapid candidate changes and closing restore only the main queue',()=>{
 const audio=setup();player.playQueue([song('a'),song('b')]);
 player.audition({...song('x'),_previewUrl:'/api/preview/abcdefghijk'});
 player.audition({...song('y'),_previewUrl:'/api/preview/zyxwvutsrqp'});
 audio.dispatchEvent(new Event('loadedmetadata'));assert.equal(audio.src,'/api/preview/zyxwvutsrqp');
 player.stopPreview();audio.dispatchEvent(new Event('loadedmetadata'));assert.equal(audio.src,'/api/stream/a');assert.equal(audio.paused,true);
 player.closePlayer();
});
test('play next precedes shuffled upcoming songs without restarting audio; undo is occurrence-specific',()=>{
 const audio=setup();player.playQueue(['a','b','c'].map(song));player.toggleShuffle();audio.currentTime=42;
 const token=player.playNext(song('b'));assert.equal(audio.currentTime,42);assert.equal(audio.src,'/api/stream/a');
 assert.deepEqual(get(player.queue).map(t=>t.id),['a','b','b','c']);
 player.undoPlayNext(token);assert.deepEqual(get(player.queue).map(t=>t.id),['a','b','c']);
 player.playNext(song('next'));player.next();assert.equal(get(player.currentTrack).id,'next');player.closePlayer();
});

test('buffering does not consume the audible ten-second audition window',t=>{
 t.mock.timers.enable({apis:['setTimeout']});
 const audio=setup();player.playQueue([song('main')]);
 player.audition({...song('candidate'),_previewUrl:'/api/preview/abcdefghijk'});
 audio.dispatchEvent(new Event('loadedmetadata'));audio.dispatchEvent(new Event('playing'));
 t.mock.timers.tick(4000);audio.currentTime=99;audio.dispatchEvent(new Event('waiting'));
 t.mock.timers.tick(12000);assert.equal(audio.paused,false);
 audio.dispatchEvent(new Event('playing'));audio.currentTime=105;t.mock.timers.tick(6000);
 assert.equal(audio.paused,true);assert.equal(get(player.playbackTiming).waitingCount,1);
 player.stopPreview();player.closePlayer();
});

test('queue edits prepare the actual next external song; paused playback and auditions stop speculation',async()=>{
 const audio=setup(),calls=[];
 globalThis.fetch=async(path,opts)=>{if(path.endsWith('/prepare'))calls.push({path,signal:opts.signal});return {ok:true,text:async()=>JSON.stringify({state:'ready'})};};
 const external=id=>({...song(id),_previewUrl:`/api/preview/${id}`});
 player.playQueue([song('local'),external('abcdefghijk'),external('second_song')]);
 audio.dispatchEvent(new Event('playing'));await new Promise(resolve=>setImmediate(resolve));
 assert.equal(calls.at(-1).path,'/api/preview/abcdefghijk/prepare');
 player.playNext(external('third_song1'));await new Promise(resolve=>setImmediate(resolve));
 assert.equal(calls.at(-1).path,'/api/preview/third_song1/prepare');
 const count=calls.length;audio.pause();player.playNext(external('fourth_song'));assert.equal(calls.length,count);
 player.audition(external('preview_one'));audio.dispatchEvent(new Event('loadedmetadata'));audio.dispatchEvent(new Event('playing'));
 assert.equal(calls.length,count);player.closePlayer();
});

test('shuffle repeat prepares the same wraparound song that next will play',async()=>{
 const audio=setup(),calls=[];
 globalThis.fetch=async(path)=>{if(path.endsWith('/prepare'))calls.push(path);return {ok:true,text:async()=>JSON.stringify({state:'ready'})};};
 const external=id=>({...song(id),_previewUrl:`/api/preview/${id}`});
 player.playQueue([external('abcdefghijk'),external('second_song')]);player.toggleShuffle();player.next();
 player.repeatMode.set('all');audio.dispatchEvent(new Event('playing'));await new Promise(resolve=>setImmediate(resolve));
 assert.equal(calls.at(-1),'/api/preview/abcdefghijk/prepare');
 player.next();assert.equal(get(player.currentTrack).id,'abcdefghijk');player.closePlayer();
});

test('a lost connection mid-song resumes from the same second, a bounded number of times',async()=>{
 const audio=setup();player._setRecoveryDelaysForTest([0,0]);
 try {
  player.playQueue([song('a')]);audio.paused=false;
  const tick=()=>new Promise(resolve=>setTimeout(resolve,5));
  for(const attempt of [1,2]){
   audio.currentTime=95;audio.error={code:2};audio.src='';
   audio.dispatchEvent(new Event('error'));
   assert.equal(get(player.playbackState),'loading');
   await tick();
   assert.equal(audio.src,'/api/stream/a',`attempt ${attempt} reloads the same song`);
   audio.currentTime=0;audio.dispatchEvent(new Event('loadedmetadata'));
   assert.equal(audio.currentTime,95,'and continues where it stopped');
  }
  audio.error={code:2};audio.dispatchEvent(new Event('error'));
  assert.equal(get(player.playbackState),'error');assert.equal(get(player.playing),false);
 } finally {player._setRecoveryDelaysForTest([1500,4000]);}
});
test('pausing during a pending reconnection is respected and unavailable songs are not retried',async()=>{
 const audio=setup();player._setRecoveryDelaysForTest([20,20]);
 try {
  player.playQueue([song('a')]);audio.paused=false;audio.currentTime=40;audio.error={code:2};
  audio.dispatchEvent(new Event('error'));
  let plays=0;audio.play=()=>{plays++;return Promise.resolve();};
  audio.pause();
  await new Promise(resolve=>setTimeout(resolve,40));
  assert.equal(plays,0);
  player.playQueue([song('b')]);audio.paused=false;audio.error={code:4};
  audio.dispatchEvent(new Event('error'));
  assert.equal(get(player.playbackState),'error');
 } finally {player._setRecoveryDelaysForTest([1500,4000]);}
});
