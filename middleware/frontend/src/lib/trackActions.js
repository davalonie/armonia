import {call,library as libApi,streamUrl} from './api.js';
import {toQueueTrack,fromQueueTrack,artUrl} from './homelab.js';
import {showContextMenu} from './stores/contextMenuStore.js';
import {showPlaylistPicker} from './stores/playlistPickerStore.js';
import {playNext,undoPlayNext,addToQueue,isPreview,trackArtUrl} from './stores/playerStore.js';
import {showToast} from './stores/toastStore.js';

const say=(e)=>showToast(e.message,'error');
const changed=()=>window.dispatchEvent(new Event('music-preferences'));

// One song menu everywhere: the song it applies to, favourite, inline rating, queue, playlist
// and download, followed by whatever the screen adds (remove from this list, select, delete...).
// `song` is a queue-shaped song (library song or external reference).
export async function songMenu(anchor,song,{extra=[],onChange=null,download=true}={}){
  const external=isPreview(song)||(song._musicTrack&&song._musicTrack.source!=='navidrome');
  const track=fromQueueTrack(song);
  const header={title:song.title||track.title,subtitle:song.artist||track.artist,art:external?artUrl(song._previewThumb||track,96):trackArtUrl(song,96)};
  const queue=[
    {label:'Reproducir a continuación',icon:'ph ph-queue',action:()=>{const token=playNext(song);showToast('Se reproducirá a continuación','info',()=>undoPlayNext(token));}},
    {label:'Añadir al final de la cola',icon:'ph ph-list-plus',action:()=>{addToQueue(song);showToast('Añadida a la cola');}},
    {label:'Añadir a playlist',icon:'ph ph-plus-circle',action:()=>showPlaylistPicker([track])},
  ];
  if(external){
    let saved={track,favorite:false,rating:0};
    try{
      const preferences=(await call('/api/track-preferences')).items;
      saved=preferences.find(p=>p.track.source===track.source&&p.track.source_id===track.source_id)||saved;
    }catch(e){return say(e);}
    const update=async change=>{
      try{saved={...saved,...change};await call('/api/track-preferences',{method:'PUT',body:JSON.stringify(saved)});changed();onChange?.();}
      catch(e){say(e);throw e;}
    };
    return showContextMenu(anchor,[
      {label:saved.favorite?'Quitar de favoritos':'Añadir a favoritos',icon:saved.favorite?'ph-fill ph-heart':'ph ph-heart',active:saved.favorite,
        action:()=>update({favorite:!saved.favorite}).then(()=>showToast(saved.favorite?'Añadida a favoritos':'Quitada de favoritos')).catch(()=>{})},
      {type:'rating',value:saved.rating||0,onRate:rating=>update({rating})},
      ...queue,...extra],header);
  }
  const starred=!!song.starred;
  showContextMenu(anchor,[
    {label:starred?'Quitar de favoritos':'Añadir a favoritos',icon:starred?'ph-fill ph-heart':'ph ph-heart',active:starred,
      action:()=>libApi(starred?'unstar':'star',{id:song.id}).then(()=>{song.starred=starred?undefined:new Date().toISOString();changed();onChange?.();showToast(starred?'Quitada de favoritos':'Añadida a favoritos');}).catch(say)},
    {type:'rating',value:song.userRating||0,onRate:async rating=>{
      try{await libApi('setRating',{id:song.id,rating});song.userRating=rating||undefined;onChange?.();}catch(e){say(e);throw e;}}},
    ...queue,
    ...(download?[{label:'Descargar archivo',icon:'ph ph-download-simple',action:()=>{const a=document.createElement('a');a.href=streamUrl(song.id);a.download=song.title||'cancion';a.click();}}]:[]),
    ...extra],header);
}

// Kept for callers that hold a stored track reference instead of a queue song.
export const externalMenu=(anchor,track,extra=[])=>songMenu(anchor,toQueueTrack(track),{extra});
