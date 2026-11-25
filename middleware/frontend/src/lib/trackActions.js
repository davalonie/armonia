import {mobile} from './native.js';
import {call,library as libApi,streamUrl,artSize} from './api.js';
import {toQueueTrack,fromQueueTrack,artUrl} from './homelab.js';
import {showContextMenu} from './stores/contextMenuStore.js';
import {showPlaylistPicker} from './stores/playlistPickerStore.js';
import {saveSheet} from './saveSong.js';
// On the phone every «Añadir a una playlist» opens the app's one sheet (AddToPlaylistSheet): several playlists and
// favourites at once, create, and a YouTube song downloaded first. The desktop keeps its picker.
export const addToPlaylist=(song,track=fromQueueTrack(song))=>mobile?saveSheet.set(song):showPlaylistPicker([track]);
import {playQueue,playNext,undoPlayNext,addToQueue,isPreview,trackArtUrl,songDownloads} from './stores/playerStore.js';
import {get} from 'svelte/store';
import {showToast} from './stores/toastStore.js';

const say=(e)=>showToast(e.message,'error');
const changed=()=>window.dispatchEvent(new Event('music-preferences'));

// One song menu everywhere: the song it applies to, favourite, inline rating, queue, playlist
// and download, followed by whatever the screen adds (remove from this list, select, delete...).
// `song` is a queue-shaped song (library song or external reference).
export async function songMenu(anchor,song,{extra=[],onChange=null,download=true}={}){
  const external=isPreview(song)||(song._musicTrack&&song._musicTrack.source!=='navidrome');
  const track=fromQueueTrack(song);
  const header={title:song.title||track.title,subtitle:song.artist||track.artist,art:external?artUrl(song._previewThumb||track,artSize(40,96)):trackArtUrl(song,artSize(40,96))};
  const playSoon=()=>{const token=playNext(song);showToast('Se reproducira a continuacion','info',()=>undoPlayNext(token));};
  const queue=[
    ...(mobile?[{label:'Reproducir',icon:'ph ph-play',action:()=>playQueue([song])}]:[]),
    {label:'Reproducir a continuacion',icon:'ph ph-queue',action:playSoon},
    ...(mobile ? [{label:'Añadir a la cola',icon:'ph ph-list-plus',action:()=>queueWithUndo(false)}] : []),
    {label:'Añadir al final de la cola',icon:'ph ph-list-plus',action:()=>queueWithUndo(true)},
    {label:'Añadir a playlist',icon:'ph ph-plus-circle',action:()=>addToPlaylist(song,track)},
  ];
  function queueWithUndo(atEnd) {
    const entry=addToQueue(song,atEnd);
    showToast(atEnd?'Añadida al final de la cola':'Añadida a la cola','info',mobile?()=>undoPlayNext(entry):null);
  }
  // A song from outside the library: on the desktop the bottom sheet, as SongMenuSheet did in the app; on the
  // phone the same pop-up as a song of a playlist (the user's choice), with its favourite and stars kept apart.
  if(external){
    let saved={track,favorite:false,rating:0},known=true;
    try{
      const preferences=(await call('/api/track-preferences')).items;
      saved=preferences.find(p=>p.track.source===track.source&&p.track.source_id===track.source_id)||saved;
    }catch(e){if(!mobile)return say(e);known=false;}
    const update=async change=>{
      try{saved={...saved,...change};await call('/api/track-preferences',{method:'PUT',body:JSON.stringify(saved)});changed();onChange?.();}
      catch(e){say(e);throw e;}
    };
    const favourite=()=>update({favorite:!saved.favorite}).then(()=>showToast(saved.favorite?'Añadida a favoritos':'Quitada de favoritos')).catch(()=>{});
    if(mobile){
      // Without the saved preferences (no connection) favourite and stars are left out rather than guessed.
      return showContextMenu(anchor,[
        {label:'Reproducir a continuacion',action:playSoon},
        ...(known?[{type:'rating',value:saved.rating||0,onRate:rating=>update({rating})}]:[]),
        {label:'Reproducir',micon:'play_arrow',action:()=>playQueue([song])},
        {label:'Añadir a la cola',micon:'queue_music',action:()=>queueWithUndo(false)},
        {label:'Añadir al final de la cola',micon:'playlist_play',action:()=>queueWithUndo(true)},
        {label:'Añadir a una playlist',micon:'playlist_add',action:()=>addToPlaylist(song,track)},
        ...(known?[{label:saved.favorite?'Quitar de favoritos':'Añadir a favoritos',micon:saved.favorite?'heart_broken':'favorite',action:favourite}]:[]),
        ...extra],header);
    }
    return showContextMenu(anchor,[
      {label:saved.favorite?'Quitar de favoritos':'Añadir a favoritos',icon:saved.favorite?'ph-fill ph-heart':'ph ph-heart',active:saved.favorite,
        action:favourite},
      {type:'rating',value:saved.rating||0,onRate:rating=>update({rating})},
      ...queue,...extra],header,{sheet:true});
  }
  const starred=!!song.starred;
  const favourite=()=>libApi(starred?'unstar':'star',{id:song.id}).then(()=>{song.starred=starred?undefined:new Date().toISOString();changed();onChange?.();showToast(starred?'Quitada de favoritos':'Añadida a favoritos');}).catch(say);
  const rating={type:'rating',value:song.userRating||0,onRate:async rating=>{
    try{await libApi('setRating',{id:song.id,rating});song.userRating=rating||undefined;onChange?.();}catch(e){say(e);throw e;}}};
  // On the phone, the menu of a song row in the app (SongRow): the same entries, order and icons.
  if(mobile){
    return showContextMenu(anchor,[
      {label:'Reproducir a continuacion',action:playSoon},
      rating,
      {label:'Reproducir',micon:'play_arrow',action:()=>playQueue([song])},
      {label:'Añadir a la cola',micon:'queue_music',action:()=>queueWithUndo(false)},
      {label:'Añadir al final de la cola',micon:'playlist_play',action:()=>queueWithUndo(true)},
      {label:'Añadir a una playlist',micon:'playlist_add',action:()=>addToPlaylist(song,track)},
      {label:starred?'Quitar de favoritos':'Añadir a favoritos',micon:starred?'heart_broken':'favorite',action:favourite},
      ...(download?[phoneDownloadItem(song)]:[]),
      ...extra],header);
  }
  showContextMenu(anchor,[
    {label:starred?'Quitar de favoritos':'Añadir a favoritos',icon:starred?'ph-fill ph-heart':'ph ph-heart',active:starred,action:favourite},
    rating,
    ...queue,
    ...(download?[{label:'Descargar archivo',icon:'ph ph-download-simple',action:()=>{const a=document.createElement('a');a.href=streamUrl(song.id);a.download=song.title||'cancion';a.click();}}]:[]),
    ...extra],header);
}

// «Descargar en el telefono» of the Kotlin menus, worded for the state the song is in on this phone.
const ON_PHONE={NONE:'Descargar en el telefono',DOWNLOADING:'Descargando… (toca para cancelar)',
  DOWNLOADED:'Quitar del telefono',IN_COLLECTION:'En el telefono (album o playlist guardados)'};
// The state comes from the native player's last report, so the menu opens at once, as in the app.
export function phoneDownloadItem(song,labels={}){
  const state=get(songDownloads)[song.id]||'NONE';
  const words={...ON_PHONE,...labels};
  return {label:words[state]||words.DOWNLOADED,micon:state==='NONE'?'download_for_offline':'download_done',disabled:state==='IN_COLLECTION',
    action:async()=>{
      try{await mobile.songDownload({id:song.id,track:song,action:state==='NONE'?'save':'remove'});changed();}
      catch(e){say(e);}
    }};
}

// Kept for callers that hold a stored track reference instead of a queue song.
export const externalMenu=(anchor,track,extra=[])=>songMenu(anchor,toQueueTrack(track),{extra});
