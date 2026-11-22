import {call,library} from './api.js';
export function uniqueAdditions(existing,incoming,key=x=>x){
  const seen=new Set(existing.map(key)), added=[];
  for(const item of incoming){const id=key(item);if(!seen.has(id)){seen.add(id);added.push(item);}}
  return {added,duplicates:incoming.length-added.length};
}
export const replaceLocal=(id,expected,songs)=>call(`/api/playlists/${encodeURIComponent(id)}/edit`,{method:'POST',body:JSON.stringify({expected,songs})});
export async function appendLocal(id,ids){
  const p=(await library('getPlaylist',{id})).playlist;
  const existing=(p.entry||[]).map(s=>s.id), result=uniqueAdditions(existing,ids);
  if(result.added.length)await replaceLocal(id,existing,[...existing,...result.added]);
  return {added:result.added.length,duplicates:result.duplicates};
}
