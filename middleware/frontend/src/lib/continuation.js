// «Continuar con música similar»: one small batch asked ahead of the end of the queue.
// Pure of the player so the races are testable: every change of context bumps the epoch
// and a batch asked under an older epoch is never handed out.
export function createContinuation(fetchBatch){
  let epoch=0,pending=null;
  const ask=request=>{
    const mine={epoch,items:null};
    mine.promise=Promise.resolve().then(()=>fetchBatch(request))
      .then(r=>r?.enabled===false?[]:(r?.items||[])).catch(()=>[]) // Any failure: the queue simply ends.
      .then(items=>(mine.items=items));
    return mine;
  };
  return {
    // A new queue, a closed player, the option switched off, a logout.
    invalidate(){epoch++;pending=null;},
    // Idempotent: one request per context, however many 'playing' events arrive.
    prepare(request){if(!pending||pending.epoch!==epoch)pending=ask(request);return pending.promise;},
    // Hands the batch out once. Empty when the context changed while it was on its way.
    async take(request){
      const mine=!pending||pending.epoch!==epoch?(pending=ask(request)):pending;
      const items=await mine.promise;
      if(mine.epoch!==epoch||pending!==mine)return [];
      pending=null;
      return items;
    },
  };
}
// Songs already queued, heard in this session or skipped as a suggestion are not offered again.
export const withoutKnown=(items,known)=>{const seen=new Set(known);return items.filter(i=>{const k=`${i.track.source}:${i.track.source_id}`;if(seen.has(k))return false;seen.add(k);return true;});};
