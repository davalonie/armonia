import { mobile } from '../native.js';
import { command, observeNativePlayer } from './nativePlayback.js';
import { writable, derived, get } from 'svelte/store';
import { call, streamUrl, coverArtUrl, library as libApi } from '../api.js';
import { ListenClock } from '../listenClock.js';
import { retainListen, flushListens } from '../listenDelivery.js';
import { accountKey, fromQueueTrack, toQueueTrack } from '../homelab.js';
import { createContinuation, withoutKnown } from '../continuation.js';
import { createTrackPreparation } from '../trackPreparation.js';
import { showToast as toast } from './toastStore.js';
import {connectMediaSession,mediaMetadata} from '../mediaSession.js';

const lastTrackKey = () => `music:last-track:${accountKey()}`;
let listen=null;

export const previewState = writable(null);
export const songDownloads = writable({});
export const serverDownloads = writable({});
export const offlineProblem = writable(null);
export const listenProblem = writable(null);
export const sleepTimer = writable({});
export const nativeQueueOrder = writable({});
export const playbackTiming = writable(null);
// 'loading' from the press until audio flows, 'error' when the source failed; '' otherwise.
export const playbackState = writable('');
let previewSnapshot=null, previewEnd=0, previewTimer=null, sourceCleanup=()=>{}, generation=0;
let startedAt=0, recentRecorded=false, waitingSince=0;
function beginTiming(preview){startedAt=performance.now();waitingSince=0;playbackTiming.set({preview,clickToPlayingMs:null,metadataMs:null,waitingCount:0,bufferMs:0,error:false});}
export const queue = writable([]);
export const currentIndex = writable(-1);
export const playing = writable(false);
export const shuffleOn = writable(false);
export const repeatMode = writable('off'); // 'off' | 'one' | 'all'
export const playbackProgress = writable({ currentTime: 0, duration: 0 });

// Derived: current track
export const currentTrack = derived(
  [queue, currentIndex, previewState],
  ([$queue, $index, $preview]) => $preview?.track || ($index >= 0 ? $queue[$index] ?? null : null),
);

let _audio = null;
let mediaCleanup=()=>{};
let _shuffledQueue = [];
let _shufflePos = -1;

// Scrobbling (Navidrome play counts / recently played / Last.fm forwarding).
// Same rule as the Android app: once per track, after half its length or four
// minutes, whichever is first; never for tracks under 30 s or for previews.
let _scrobbleId = null;
let _scrobbled = false;

function _scrobble(id, submission) {
  libApi('scrobble', { id, submission: String(submission) }).catch(() => {});
}

function _onTrackStarted(track) {
  if(get(previewState)){listen=null;_scrobbleId=null;return;}
  _scrobbleId = track && !isPreview(track) ? track.id : null;
  _scrobbled = false;
  listen=track && !get(previewState) ? {clock:new ListenClock(),id:crypto.randomUUID(),owner:accountKey(),started:Math.floor(Date.now()/1000),track:fromQueueTrack(track)} : null;
  if (_scrobbleId) _scrobble(_scrobbleId, false);
}

function _maybeScrobble(currentTime, duration) {
  if (!listen || !_audio || get(previewState)) return;
  listen.clock.sample(currentTime,performance.now(),!_audio.paused && !_audio.ended,_audio.seeking);
  if (!listen.clock.ready(duration)) return;
  const retained=retainListen(listen.owner,{id:listen.id,track:{...listen.track,duration:duration>0?duration:null},
    started_at:listen.started,listened_seconds:listen.clock.seconds});
  if (!retained) {
    listen.clock.submitted=false; // Retry the same event if local storage recovers.
    if (!listen.storageError) toast('No se pudo guardar la escucha en este navegador.', 'error');
    listen.storageError=true;
  }
  if (_scrobbleId && !_scrobbled) { _scrobbled=true; _scrobble(_scrobbleId,true); }
}

export function isPreview(track) {
  return !!track?._previewUrl;
}

export function trackArtUrl(track, size) {
  if (!track) return '';
  if (isPreview(track)) return track._previewThumb || '';
  return track.coverArt ? coverArtUrl(track.coverArt, size) : '';
}

// A lost connection is retried from the same position after these delays (per song).
let RECOVERY_DELAYS=[1500,4000];
const recovery={attempts:0,timer:0,at:0};
function resetRecovery(){clearTimeout(recovery.timer);recovery.attempts=0;}
export function _setRecoveryDelaysForTest(delays){RECOVERY_DELAYS=delays;}
const sourceUrl=track=>isPreview(track)?track._previewUrl:streamUrl(track.id);

export function initAudio(audioEl) {
  if (mobile) return observeNativePlayer({queue, currentIndex, playing, playbackProgress, shuffleOn, repeatMode, continueSimilar, playbackState, previewState, sleepTimer, nativeQueueOrder, songDownloads, serverDownloads, offlineProblem, listenProblem});
  preparation.reset();
  sourceCleanup(); clearTimeout(previewTimer); previewState.set(null); previewSnapshot=null;
  _audio = audioEl;

  // Lock screen, notification and headset buttons. A preview is not announced as the queue.
  const nav=typeof navigator==='undefined'?null:navigator;
  const media=connectMediaSession(nav,typeof MediaMetadata==='undefined'?undefined:MediaMetadata,{
    play:()=>{if(_audio.paused)togglePlayPause();},pause:()=>{if(!_audio.paused)togglePlayPause();},
    next:()=>next(),prev:()=>prev(),seekTo:seconds=>{if(_audio.duration)_audio.currentTime=Math.min(Math.max(seconds,0),_audio.duration);},
  });
  mediaCleanup();
  const stopTrack=currentTrack.subscribe(track=>media.update(mediaMetadata(track,trackArtUrl(track,512))));
  const report=()=>media.position(_audio.duration,_audio.currentTime,_audio.playbackRate);
  const onPlayState=()=>{media.playing(!_audio.paused);report();};
  for(const name of ['play','pause','ended'])_audio.addEventListener(name,onPlayState);
  for(const name of ['durationchange','seeked','ratechange'])_audio.addEventListener(name,report);
  mediaCleanup=()=>{stopTrack();for(const name of ['play','pause','ended'])_audio?.removeEventListener(name,onPlayState);for(const name of ['durationchange','seeked','ratechange'])_audio?.removeEventListener(name,report);};

  _audio.addEventListener('playing', () => {
    const context=get(currentTrack)?._playlist;
    if(context && !get(previewState) && !recentRecorded){recentRecorded=true;void call('/api/recent-playlists',{method:'POST',body:JSON.stringify(context)}).catch(()=>{});}
    const now=performance.now();
    playbackTiming.update(t=>t?{...t,clickToPlayingMs:t.clickToPlayingMs??(startedAt?now-startedAt:null),bufferMs:t.bufferMs+(waitingSince?now-waitingSince:0)}:t);
    startedAt=0;waitingSince=0;playbackState.set('');
    if(!get(previewState)){prepareNext();prepareContinuation();}
    if(get(previewState)){previewState.update(p=>({...p,status:'playing'}));clearTimeout(previewTimer);previewTimer=setTimeout(()=>pausePreview(),Math.max(0,previewEnd-_audio.currentTime)*1000);}
  });
  _audio.addEventListener('loadedmetadata',()=>{if(startedAt)playbackTiming.update(t=>t?{...t,metadataMs:performance.now()-startedAt}:t);});
  _audio.addEventListener('waiting',()=>{playbackState.set('loading');clearTimeout(previewTimer);if(!waitingSince){waitingSince=performance.now();playbackTiming.update(t=>t?{...t,waitingCount:t.waitingCount+1}:t);}});
  _audio.addEventListener('play', () => { playing.set(true); if(!listen) _onTrackStarted(get(currentTrack)); _maybeScrobble(_audio.currentTime,_audio.duration); });
  _audio.addEventListener('seeking',()=>_maybeScrobble(_audio.currentTime,_audio.duration));
  _audio.addEventListener('error',()=>{
    preparation.cancel();
    const lost=_audio.error?.code===2; // MEDIA_ERR_NETWORK: the transfer broke, the song itself may be fine.
    const wanted=!_audio.paused||get(playbackState)==='loading';
    if(lost&&wanted&&!get(previewState)&&recovery.attempts<RECOVERY_DELAYS.length){
      // Resume from the same second after a lost connection, a bounded number of times per song.
      const epoch=generation,at=_audio.currentTime,track=get(currentTrack);
      recovery.at=at;
      playbackState.set('loading');
      if(!recovery.attempts)toast('Se perdio la conexion con el servidor. Reintentando…');
      recovery.timer=setTimeout(()=>{
        if(epoch!==generation||!track||get(currentTrack)!==track)return;
        if(at>0)_audio.addEventListener('loadedmetadata',()=>{if(epoch===generation)_audio.currentTime=at;},{once:true});
        _audio.src=sourceUrl(track);_audio.load();
        _audio.play().catch(()=>{});
      },RECOVERY_DELAYS[recovery.attempts++]);
      return;
    }
    playbackTiming.update(t=>t?{...t,error:true}:t);playing.set(false);playbackState.set('error');
    toast(lost?'Se perdio la conexion con el servidor. Pulsa reproducir para reintentar.':'Cancion no disponible. Puedes saltar a la siguiente.','error');
  });
  _audio.addEventListener('pause', () => {
    clearTimeout(recovery.timer); // Pausing (or unplugging headphones) wins over a pending reconnection.
    preparation.cancel();
    playing.set(false);
    clearTimeout(previewTimer);
    if(get(previewState)) previewState.update(p=>({...p,status:'paused'}));
    _maybeScrobble(_audio.currentTime,_audio.duration);
    saveLastTrack();
  });
  _audio.addEventListener('ended', onEnded);
  _audio.addEventListener('timeupdate', () => {
    if(recovery.attempts&&_audio.currentTime-recovery.at>30)recovery.attempts=0;
    playbackProgress.set({
      currentTime: _audio.currentTime,
      duration: _audio.duration || 0,
    });
    if(get(previewState) && _audio.currentTime>=previewEnd) pausePreview();
    _maybeScrobble(_audio.currentTime, _audio.duration || 0);
  });

  window.addEventListener('beforeunload', saveLastTrack);
  restoreLastTrack();
  void flushListens();
}

// External songs need their source resolved before the first byte (about 1.5 s). Asking the
// server to resolve the next one while the current plays removes that wait from the transition.
// One song ahead only; the server may buffer audio in memory. It is not a listen.
const preparation=createTrackPreparation((id,signal)=>call(`/api/preview/${id}/prepare`,{method:'POST',signal}),{ownerNow:accountKey});
const externalId=track=>track?._previewUrl?.match(/^\/api\/preview\/([\w-]{11})$/)?.[1];
function prepareNext(){
  if(!_audio||_audio.paused||get(previewState)){preparation.cancel();return;}
  preparation.prepare(accountKey(),externalId(upcomingTrack()));
}
function upcomingTrack(){
  const q=get(queue);
  if(get(repeatMode)==='one')return null;
  if(get(shuffleOn)&&_shuffledQueue.length)return q[_shuffledQueue[_shufflePos+1]]||(get(repeatMode)==='all'?q[_shuffledQueue[0]]:null);
  return q[get(currentIndex)+1]||(get(repeatMode)==='all'?q[0]:null);
}
function onEnded(){
  if(get(previewState)){pausePreview();return;}
  if (get(repeatMode) === 'one') {
    _onTrackStarted(get(currentTrack));
    _audio.currentTime = 0;
    _audio.play().catch(() => {});
  } else if (upcomingTrack() || !canContinue()) {
    next();
  } else {
    void continueSimilarly();
  }
}

// «Continuar con musica similar». Only a natural end of the queue asks for it: pause, stop,
// logout and a lost connection never reach this code. The original playlist is not touched:
// suggestions are appended to the playback snapshot and flagged `_auto`.
export const continueSimilar = writable(true);
const continuation=createContinuation(body=>call('/api/home/continue',{method:'POST',body:JSON.stringify(body)}));
const heard=[],dismissed=[];
let continuing=false;
const trackKey=t=>{const m=fromQueueTrack(t);return `${m.source}:${m.source_id}`;};
const canContinue=()=>get(continueSimilar)&&get(repeatMode)==='off'&&!get(previewState)&&!!accountKey();
function continuationRequest(){
  const q=get(queue),at=get(currentIndex);
  const artists=[...new Set([q[at],...q.slice(Math.max(0,at-2),at).reverse()].filter(Boolean).map(t=>t.artist).filter(Boolean))].slice(0,3);
  const videoId=q[at]&&externalId(q[at]);
  return {artists,...(videoId?{videoId}:{}),exclude:[...new Set([...q.map(trackKey),...heard,...dismissed])].slice(-600)};
}
function prepareContinuation(){
  if(!canContinue()||upcomingTrack())return;
  const mine=generation,owner=accountKey();
  void continuation.prepare(continuationRequest()).then(items=>{
    // Resolve the first suggestion's source ahead of time, as for any next song.
    if(items[0]&&mine===generation&&owner===accountKey()&&!_audio?.paused&&canContinue()&&!upcomingTrack())
      preparation.prepare(owner,externalId(toQueueTrack(items[0].track,items[0].cover)));
  });
}
async function continueSimilarly(){
  if(continuing)return; // A second 'ended' for the same song.
  continuing=true;
  const mine=generation,owner=accountKey();
  try{
    const items=await continuation.take(continuationRequest());
    // Anything the user did while the answer was on its way wins over the suggestion.
    if(mine!==generation||owner!==accountKey()||!_audio?.ended)return;
    if(!canContinue()){if(get(repeatMode)!=='off')onEnded();return;} // Repeat was switched on meanwhile.
    if(upcomingTrack()){next();return;} // A song was added by hand meanwhile: it goes first.
    const fresh=withoutKnown(items,[...get(queue).map(trackKey),...dismissed]);
    if(!fresh.length)return;
    const start=get(queue).length;
    queue.update(q=>[...q,...fresh.map(i=>({...toQueueTrack(i.track,i.cover),_auto:true,_from:'Musica similar'}))]);
    if(get(shuffleOn))_shuffledQueue.push(...fresh.map((_,n)=>start+n));
    next();
  }finally{continuing=false;}
}
export function setContinueSimilar(on){
  continueSimilar.set(!!on);
  continuation.invalidate(); preparation.cancel();
  if(!on){ // Suggestions not yet played leave the queue; the one sounding now is the user's to stop.
    const at=get(currentIndex),q=get(queue);
    for(let i=q.length-1;i>at;i--)if(q[i]._auto)removeFromQueue(i);
  }
}
export async function loadPlaybackSettings(){
  try{continueSimilar.set((await call('/api/home/settings')).continue_similar!==false);}catch{}
  continuation.invalidate();
}
export async function saveContinueSimilar(on){
  if (mobile) return command('similar', {enabled:on});
  const before=get(continueSimilar);
  setContinueSimilar(on);
  try{await call('/api/home/settings',{method:'PUT',body:JSON.stringify({continue_similar:!!on})});}
  catch(e){setContinueSimilar(before);throw e;}
}

export function prepareTrack(track){
  if (mobile) {
    const videoId = externalId(track);
    if (videoId) void mobile.command({action:'prepare',videoId}).catch(()=>{});
    return;
  }
  // Browsing another list must not displace preparation of the playing queue.
  if(get(previewState)||(_audio&&!_audio.paused))return;
  preparation.prepare(accountKey(),externalId(track));
}

function _load(autoplay=true) {
  preparation.cancel(); resetRecovery();
  sourceCleanup(); generation++; beginTiming(false); recentRecorded=false;
  const $queue = get(queue);
  const $index = get(currentIndex);
  const track = $queue[$index];
  if (!track || !_audio) return;
  heard.push(trackKey(track)); if(heard.length>300)heard.shift();
  _audio.src = sourceUrl(track);
  playbackState.set(autoplay?'loading':'');
  if(autoplay) _audio.play().catch(()=>toast('Pulsa reproducir para iniciar el audio.'));
  else _audio.pause();
  _onTrackStarted(track);
  saveLastTrack();
}

export async function beginPlayRequest() {
  return mobile ? (await mobile.command({action:'beginPlay'})).epoch : undefined;
}

export function swipeTrack(direction) {
  if (mobile) return command('step',{direction});
  return direction > 0 ? next() : prev();
}

export function playQueue(tracks, startIndex = 0, epoch = undefined) {
  if (mobile) {
    if (tracks.length) void command('play', {tracks, index:startIndex, epoch, playlistId:tracks[startIndex]?._playlist?.id,
      kind:tracks[startIndex]?._playlist?.kind, from:tracks[startIndex]?._from});
    return;
  }
  if (!tracks.length || !Number.isInteger(startIndex) || startIndex < 0 || startIndex >= tracks.length) return;
  stopPreview(false);
  continuation.invalidate();
  queue.set([...tracks]); // Playback is a snapshot, independent from editor mutations.
  currentIndex.set(startIndex);
  if (get(shuffleOn)) _buildShuffleOrder(startIndex, tracks.length);
  _load();
}

// Normal external playback remains a full track; explicit audition is separate.
export function playPreviewTrack(track) {
  if (track) playQueue([track]);
}

export function audition(track, resumeAfter = false) {
  if (mobile) {
    const current = get(previewState)?.track;
    if (current && (current.id === track.id || (current._musicTrack && current._musicTrack.source === track._musicTrack?.source && current._musicTrack.source_id === track._musicTrack?.source_id))) return stopPreview();
    return command('audition', {track, resumeAfter});
  }
  if(!track || !_audio) return;
  if(get(previewState)?.track?._previewUrl===track._previewUrl && get(previewState)?.track?.id===track.id){
    if(!_audio.paused || get(previewState)?.status==='loading') {pausePreview();return;}
  }
  preparation.cancel();
  if(!previewSnapshot) previewSnapshot={time:_audio.currentTime,listen,scrobbleId:_scrobbleId,scrobbled:_scrobbled};
  sourceCleanup(); clearTimeout(previewTimer); const epoch=++generation;
  _audio.pause(); listen=null; beginTiming(true);
  previewState.set({track,status:'loading',note:'Fragmento central · 10 segundos'});
  const url=isPreview(track)?track._previewUrl:streamUrl(track.id);
  const ready=()=>{
    if(epoch!==generation || !get(previewState))return;
    const duration=Number.isFinite(_audio.duration)?_audio.duration:track.duration;
    const middle=duration>10?Math.max(0,duration/2-5):0;
    previewEnd=Math.min(duration||10,middle+10);
    try{_audio.currentTime=middle;}catch{previewEnd=10;previewState.update(p=>({...p,note:'Esta fuente solo permite escuchar desde el inicio'}));}
    _audio.play().catch(()=>{if(epoch===generation)previewState.update(p=>p?{...p,status:'paused'}:p);});
  };
  _audio.addEventListener('loadedmetadata',ready,{once:true});
  sourceCleanup=()=>_audio?.removeEventListener('loadedmetadata',ready);
  _audio.src=url; _audio.load();
}

export function pausePreview(){
  if (mobile) return get(playing) && get(previewState) ? command('toggle') : undefined;
  if(!get(previewState))return;
  if(get(previewState)?.status==='loading'){sourceCleanup();generation++;}
  clearTimeout(previewTimer); _audio?.pause();
  previewState.update(p=>p?{...p,status:'paused'}:p);
}

export function stopPreview(restore=true){
  if (mobile) return command('stopAudition', {resume:restore});
  if(!previewSnapshot)return;
  sourceCleanup(); sourceCleanup=()=>{}; clearTimeout(previewTimer); const epoch=++generation;
  _audio?.pause();
  const saved=previewSnapshot;previewSnapshot=null;previewState.set(null);listen=saved.listen;_scrobbleId=saved.scrobbleId;_scrobbled=saved.scrobbled;
  if(restore && _audio){
    const track=get(currentTrack);
    if(track){
      const ready=()=>{if(epoch===generation)_audio.currentTime=saved.time;};
      _audio.addEventListener('loadedmetadata',ready,{once:true});
      sourceCleanup=()=>_audio?.removeEventListener('loadedmetadata',ready);
      _audio.src=isPreview(track)?track._previewUrl:streamUrl(track.id);_audio.load();
    }else{_audio.removeAttribute('src');_audio.load();}
  }
}

export function playNext(track){
  if (mobile) return command('playNext', {track});
  if(!track)return null;
  const token=crypto.randomUUID(), entry={...track,_queueEntry:token};
  const index=Math.max(0,get(currentIndex)+1);
  queue.update(q=>[...q.slice(0,index),entry,...q.slice(index)]);
  if(get(currentIndex)<0)currentIndex.set(0);
  if(get(shuffleOn)){
    _shuffledQueue=_shuffledQueue.map(i=>i>=index?i+1:i);
    _shuffledQueue.splice(_shufflePos+1,0,index);
  }
  prepareNext();
  return token;
}
export function undoPlayNext(token){
  if (mobile) return Promise.resolve(token).then(entry => entry?.token && command('undo', {token:entry.token}));
  const index=get(queue).findIndex(t=>t._queueEntry===token);
  if(index>=0)removeFromQueue(index);
}

/** Play from a list header, as in the app: in order, or, with shuffle on, from a random song of the list. */
export function playList(tracks, epoch = undefined) {
  if (!tracks.length) return;
  playQueue(tracks, get(shuffleOn) ? firstShuffled(tracks.length) : 0, epoch);
}

export const firstShuffled = (length, random = Math.random) => Math.min(length - 1, Math.floor(random() * length));

export function next() {
  if (mobile) return command('next');
  stopPreview();
  const leaving=get(currentTrack);
  // Skipping a suggestion early means "not this one": it is not offered again in this session.
  if(leaving?._auto&&_audio&&!_audio.ended&&_audio.currentTime<30){dismissed.push(trackKey(leaving));if(dismissed.length>200)dismissed.shift();}
  if (get(shuffleOn) && _shuffledQueue.length) {
    if (_shufflePos < _shuffledQueue.length - 1) {
      _shufflePos++;
      currentIndex.set(_shuffledQueue[_shufflePos]);
      _load();
    } else if (get(repeatMode) === 'all') {
      _buildShuffleOrder(_shuffledQueue[0], get(queue).length);
      currentIndex.set(_shuffledQueue[0]);
      _load();
    }
  } else {
    const $index = get(currentIndex);
    const qLen = get(queue).length;
    if ($index < qLen - 1) {
      currentIndex.update(i => i + 1);
      _load();
    } else if (get(repeatMode) === 'all') {
      currentIndex.set(0);
      _load();
    }
  }
}

export function prev() {
  if (mobile) return command('previous');
  stopPreview();
  if (_audio && _audio.currentTime > 3) {
    _audio.currentTime = 0;
    return;
  }
  if (get(shuffleOn) && _shuffledQueue.length) {
    if (_shufflePos > 0) {
      _shufflePos--;
      currentIndex.set(_shuffledQueue[_shufflePos]);
      _load();
    }
  } else {
    const $index = get(currentIndex);
    if ($index > 0) {
      currentIndex.update(i => i - 1);
      _load();
    }
  }
}

export function togglePlayPause() {
  if (mobile) return command('toggle');
  if (!_audio) return;
  if(get(previewState)){if(_audio.paused)audition(get(previewState).track);else pausePreview();return;}
  if(!_audio.src && get(currentTrack)){_load();return;}
  _audio.paused ? _audio.play().catch(()=>{}) : _audio.pause();
}

export function seekFraction(fraction) {
  if (mobile) return command('seek', {fraction});
  if (_audio && _audio.duration) {
    _audio.currentTime = fraction * _audio.duration;
  }
}

export function toggleRepeat() {
  if (mobile) return command('repeat');
  const modes = ['off', 'one', 'all'];
  const cur = get(repeatMode);
  repeatMode.set(modes[(modes.indexOf(cur) + 1) % modes.length]);
  prepareNext();
}

export function toggleShuffle() {
  if (mobile) return command('shuffle');
  const on = !get(shuffleOn);
  shuffleOn.set(on);
  if (on) {
    const $q = get(queue);
    _buildShuffleOrder(get(currentIndex), $q.length);
  }
  prepareNext();
}

export function toggleLike() {
  if (mobile) return command('like');
  return toggleTrackLike(get(currentTrack));
}

export async function toggleTrackLike(track) {
  if (!track || isPreview(track)) return;
  const isLiked = !!track.starred;
  try {
    await libApi(isLiked ? 'unstar' : 'star', { id: track.id });
    queue.update($q => {
      const updated = [...$q];
      const index = updated.indexOf(track);
      if (index === -1) return $q; // The queue may have been replaced while awaiting the API.
      updated[index] = {
        ...track,
        starred: isLiked ? undefined : new Date().toISOString(),
      };
      return updated;
    });
  } catch (e) {
    console.error('like toggle failed:', e);
  }
}

export function addToQueue(track, atEnd = false) {
  if (mobile) return command(atEnd ? 'end' : 'add', {track});
  if (!track) return;
  const $q = get(queue);
  if ($q.length === 0 || get(currentIndex) === -1) {
    playQueue([track], 0);
    return;
  }
  queue.update(q => [...q, track]);
  if (get(shuffleOn)) _shuffledQueue.push($q.length);
  prepareNext();
}

export function removeFromQueue(qIdx) {
  if (mobile) return command('remove', {index:qIdx});
  const $index = get(currentIndex);
  if (!Number.isInteger(qIdx) || qIdx < 0 || qIdx >= get(queue).length || qIdx === $index) return;
  queue.update(q => {
    const updated = [...q];
    updated.splice(qIdx, 1);
    return updated;
  });
  if (qIdx < $index) currentIndex.update(i => i - 1);
  _shuffledQueue = _shuffledQueue.filter(i => i !== qIdx).map(i => i > qIdx ? i - 1 : i);
  _shufflePos = _shuffledQueue.indexOf(get(currentIndex));
  prepareNext();
}

export function reorderQueue(fromIdx, toIdx) {
  if (mobile) return command('move', {index:fromIdx, to:toIdx});
  const old = get(queue), active = get(currentIndex);
  if (![fromIdx,toIdx].every(Number.isInteger) || fromIdx < 0 || fromIdx >= old.length || toIdx < 0 || toIdx > old.length) return;
  const order = old.map((_, i) => i);
  const [moved] = order.splice(fromIdx, 1);
  order.splice(fromIdx < toIdx ? toIdx - 1 : toIdx, 0, moved);
  queue.set(order.map(i => old[i]));
  currentIndex.set(order.indexOf(active));
  _shuffledQueue = _shuffledQueue.map(i => order.indexOf(i));
  prepareNext();
}

export function clearUpcoming() {
  if (mobile) return command('clear');
  queue.update($q => $q.slice(0, get(currentIndex) + 1));
  _shuffledQueue = _shuffledQueue.filter(i => i < get(queue).length);
  _shufflePos = _shuffledQueue.indexOf(get(currentIndex));
  prepareNext();
}

export function saveLastTrack() {
  if (mobile) return;
  if(get(previewState))return;
  const track = get(currentTrack);
  if (!track || isPreview(track)) {
    try { localStorage.removeItem(lastTrackKey()); } catch {}
    return;
  }
  try {
    localStorage.setItem(
      lastTrackKey(),
      JSON.stringify({ track, currentTime: _audio?.currentTime ?? 0 }),
    );
  } catch {}
}

export function closePlayer() {
  if (mobile) return command('close');
  preparation.reset();
  stopPreview(false); sourceCleanup(); generation++; clearTimeout(previewTimer);
  continuation.invalidate(); heard.length=0; dismissed.length=0;
  if (_audio) {
    _audio.pause();
    _audio.removeAttribute('src');
    _audio.load(); // Release the active HTTP stream, not merely pause decoding.
  }
  listen=null;
  try { localStorage.removeItem(lastTrackKey()); } catch {}
  queue.set([]);
  currentIndex.set(-1);
  playbackProgress.set({ currentTime: 0, duration: 0 });
}

function restoreLastTrack() {
  try {
    const saved = localStorage.getItem(lastTrackKey());
    if (!saved) return;
    const { track, currentTime } = JSON.parse(saved);
    if (!track?.id) return;
    queue.set([track]);
    currentIndex.set(0);
    if (_audio) {
      _audio.src = streamUrl(track.id);
      if (currentTime > 0) {
        _audio.addEventListener(
          'loadedmetadata',
          () => {
            _audio.currentTime = Math.min(currentTime, (_audio.duration || currentTime) - 1);
          },
          { once: true },
        );
      }
    }
  } catch {
    localStorage.removeItem(lastTrackKey());
  }
}

function _buildShuffleOrder(startIdx, length) {
  const indices = Array.from({ length }, (_, i) => i).filter(i => i !== startIdx);
  for (let i = indices.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [indices[i], indices[j]] = [indices[j], indices[i]];
  }
  _shuffledQueue = [startIdx, ...indices];
  _shufflePos = 0;
}
