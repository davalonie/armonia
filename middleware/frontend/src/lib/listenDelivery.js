import { call } from './api.js';
import { accountKey } from './homelab.js';
let flushing=false;
const key=owner=>`music:listens:${owner}`;
const pendingPrefix=owner=>key(owner)+':event:';
const rejectedPrefix=owner=>key(owner)+':rejected-event:';

function entries(prefix) {
  const result=[];
  for(let i=0;i<localStorage.length;i++) {
    const name=localStorage.key(i);
    if(name?.startsWith(prefix)) {
      const raw=localStorage.getItem(name);
      if(raw!==null) result.push([name,JSON.parse(raw)]);
    }
  }
  return result;
}
function storeEvent(owner,event) {
  if(!event || typeof event.id!=='string' || !event.id) throw new Error('Invalid listening event');
  const name=pendingPrefix(owner)+event.id, raw=JSON.stringify(event);
  const previous=localStorage.getItem(name);
  if(previous!==null && previous!==raw) throw new Error('Conflicting listening event');
  localStorage.setItem(name,raw);
}
function migrate(owner) {
  const previous=localStorage.getItem(key(owner));
  if(previous===null) return;
  const values=JSON.parse(previous);
  if(!Array.isArray(values)) throw new Error('Invalid listening outbox');
  // One key per UUID avoids read/modify/write loss between browser tabs. Copy
  // first; if storage is full or corrupt, preserve the original for recovery.
  for(const event of values) storeEvent(owner,event);
  localStorage.removeItem(key(owner));
}
export function rejectedListens(owner=accountKey()) {
  try {
    return entries(rejectedPrefix(owner)).length + JSON.parse(localStorage.getItem(key(owner)+':rejected') || '[]').length;
  } catch {return 0;}
}
export function retainListen(owner, event) {
  if (!owner || owner!==accountKey()) return false;
  try {
    migrate(owner);
    if (entries(pendingPrefix(owner)).length>=500) return false;
    storeEvent(owner,event);
  } catch {return false;}
  void flushListens(); return true;
}
export async function flushListens() {
  const owner=accountKey();
  if (!owner || flushing) return;
  flushing=true;
  try {
    migrate(owner);
    for (const [name,event] of entries(pendingPrefix(owner)).slice(0,25)) {
      if (owner!==accountKey()) break;
      const controller=new AbortController();
      const timer=setTimeout(()=>controller.abort(),15000);
      try {
        await call('/api/listening/events', {method:'POST',headers:{'X-Music-Owner':owner},body:JSON.stringify(event),signal:controller.signal});
      } catch(error) {
        // An account-change 409 is recoverable by signing in as the owner.
        // Only the explicit immutable-event conflict is a permanent 409.
        if (error.status!==422 && !(error.status===409 && error.detail==='event id already used with different content')) throw error;
        const prefix=rejectedPrefix(owner);
        localStorage.setItem(prefix+event.id,JSON.stringify({event,status:error.status}));
        for(const [old] of entries(prefix).slice(0,-500)) localStorage.removeItem(old);
      } finally {clearTimeout(timer);}
      // Never rewrite an entire queue: another tab may append while we await.
      localStorage.removeItem(name);
    }
  } catch { /* Preserve exact UUID/payload for reconnect and storage recovery. */ }
  finally {flushing=false;}
}
if (typeof window!=='undefined') {
  window.addEventListener('online',()=>void flushListens());
  setInterval(()=>void flushListens(),30000);
}
