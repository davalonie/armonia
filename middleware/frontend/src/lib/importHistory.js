// A processed position can still need a choice, retry or library scan. Neither
// `status: done` nor current === total is a completion criterion on its own.
const unfinishedStates = new Set(['review','not_found','search_failed','download_failed','source_unavailable','pending','searching','downloading','indexing']);
const count = value => Number.isInteger(value) && value >= 0 ? value : 0;

export function importWorkState(job) {
  if (!job) return {pending:false, label:''};
  if (job.hasPendingWork === false) return {pending:false, label:'Finalizada'};
  const items = Array.isArray(job.items) ? job.items : null;
  const states = items?.reduce((all,item)=>{all[item.state]=(all[item.state]||0)+1;return all;},{});
  const indexing = states ? count(states.indexing) : count(job.indexing);
  const review = states ? count(states.review) : count(job.needsReview);
  const errors = states ? ['not_found','search_failed','download_failed'].reduce((n,state)=>n+count(states[state]),0) : count(job.errors)||count(job.failed);
  const queued = states ? count(states.pending)+count(states.searching)+count(states.downloading) : count(job.queued)+count(job.inProgress);
  const unavailable = states ? count(states.source_unavailable) : count(job.unavailable);
  const legacySkipped = items ? items.filter(item=>item.state==='skipped'&&item.manualPending!==true).length
    : Number.isInteger(job.legacySkipped) ? count(job.legacySkipped) : count(job.skipped);
  const terminal = states ? count(states.ready)+count(states.skipped) : count(job.ready)+count(job.skipped);
  const accountedFor = Number.isInteger(job.total) && terminal+indexing===job.total && (!items||items.length===job.total);
  if (job.status==='running') return {pending:true,label:'En curso'};
  if (job.error || job.status==='error' || job.status==='paused' || job.resumeAvailable) return {pending:true,label:'Necesita recuperacion'};
  if (review) return {pending:true,label:`${review} por revisar`};
  if (errors) return {pending:true,label:`${errors} con error`};
  if (indexing) return {pending:true,label:`${indexing} esperando la biblioteca`,onlyIndexing:accountedFor&&!queued&&!unavailable&&!legacySkipped&&job.sourceInfo?.source_complete===true&&!count(job.notRetrieved)};
  if (queued) return {pending:true,label:`${queued} por procesar`};
  if (unavailable) return {pending:true,label:`${unavailable} sin recuperar de la fuente`};
  if (legacySkipped) return {pending:true,label:`${legacySkipped} omitidas por resolver`};
  if (job.sourceInfo?.source_complete!==true || count(job.notRetrieved)>0) return {pending:true,label:'Fuente por completar'};
  if (job.hasPendingWork===true) return {pending:true,label:'Necesita revision'};
  // Older APIs have no explicit completion flag. Only fully accounted, terminal
  // positions with confirmed source coverage may leave the pending selector.
  const complete = job.status==='done' && Number.isInteger(job.total) && job.total>=0 && terminal===job.total
    && (!items || (items.length===job.total && !items.some(item=>unfinishedStates.has(item.state))));
  return complete ? {pending:false,label:'Finalizada'} : {pending:true,label:'Estado por comprobar'};
}

export function importHistoryGroups(history, active=null) {
  const latest = new Map((history||[]).map(job=>[job.importId,job]));
  if (active?.importId) {
    const saved=latest.get(active.importId);
    const revision=job=>Number.isInteger(job?.revision)?job.revision:-1;
    if(!saved||revision(active)>=revision(saved)) latest.set(active.importId,active);
  }
  const pending=[], completed=[];
  for(const job of latest.values()) (importWorkState(job).pending?pending:completed).push(job);
  return {pending,completed};
}
