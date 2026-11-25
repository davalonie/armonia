// Every kind of song list ends in the same row shape and the same queue, wherever it is opened from
// (Inicio, Buscar, Biblioteca). A row is {queue, art}: a queue-shaped song and its small artwork.
import {call,library,coverArtUrl,artSize} from './api.js';
import {api,toQueueTrack,artUrl} from './homelab.js';

export const localRow=s=>({queue:s,art:s.coverArt?coverArtUrl(s.coverArt,artSize(48,96)):''});
export const refRow=i=>({queue:toQueueTrack(i.track,i.cover),art:artUrl({...i.track,cover:i.cover},artSize(48,96))});
export const count=n=>`${n} ${n===1?'cancion':'canciones'}`;

export const loaders={
  liked:async()=>{
    const [starred,external]=await Promise.all([library('getStarred2'),call('/api/track-preferences').catch(()=>({items:[]}))]);
    return {rows:[...(starred.starred2?.song||[]).map(localRow),...external.items.filter(p=>p.favorite).map(p=>refRow({track:p.track}))]};
  },
  local:async e=>({rows:((await library('getPlaylist',{id:e.id})).playlist?.entry||[]).map(localRow)}),
  mixed:async e=>({rows:(await api.playlist(e.id)).items.map(refRow)}),
  album:async e=>({rows:((await library('getAlbum',{id:e.id})).album?.song||[]).map(localRow)}),
  generated:async e=>{
    const list=await api.homePlaylist(e.id);
    return {rows:list.items.map(refRow),state:list.state,notice:list.error||'',description:list.description,updated:list.updated,covers:list.covers};
  },
};
// Lists whose playback counts as "recently played" on Inicio.
export const context=e=>['local','mixed','generated'].includes(e.type)?{kind:e.type,id:e.id}:null;

export const likedEntry={type:'liked',id:'liked',title:'Tus favoritos',variant:'liked',eyebrow:'Lista'};
export const albumEntry=a=>({type:'album',id:a.id,title:a.name,covers:a.coverArt?[coverArtUrl(a.coverArt,300)]:[],variant:'plain',eyebrow:'Album',description:a.artist});
// A library playlist: native (Navidrome) or mixed (may hold external songs). One concept for the user.
export const playlistEntry=p=>({type:p.kind,id:p.id,title:p.name,variant:'plain',eyebrow:'Lista',
  covers:p.coverArt?[coverArtUrl(p.coverArt,300)]:(p.covers||[]),songs:p.songCount??p.item_count??null});
