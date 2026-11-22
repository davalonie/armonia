import { writable } from 'svelte/store';
import { importStatus, getSession } from '../api.js';
export const activeImport = writable(null);
let timer = null, generation = 0;
export function startImport(importId, name, total, initial=null) {
  const epoch=++generation, owner=getSession()?.userId;
  if(timer)clearTimeout(timer);
  activeImport.set(initial||{importId,name,status:'running',total,current:0,downloaded:0,existing:0,failed:0,failures:[]});
  async function poll(){
    if(epoch!==generation||getSession()?.userId!==owner)return;
    let next=true;
    try{
      const job=await importStatus(importId);
      if(epoch!==generation||getSession()?.userId!==owner)return;
      activeImport.set(job);next=job.status==='running';
    }catch(e){
      if(epoch!==generation||getSession()?.userId!==owner)return;
      activeImport.update(job=>({...job,connectionError:true}));
      if([401,403,404,409].includes(e.status))next=false;
    }
    if(next)timer=setTimeout(poll,2000);
  }
  void poll();
}
export function clearImport(){generation++;if(timer)clearTimeout(timer);timer=null;activeImport.set(null);}
