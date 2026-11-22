<script>
  import PreviewControls from './PreviewControls.svelte';
  import {onMount,tick} from 'svelte';
  import {call, library, importStatus, getSession} from '../lib/api.js';
  import {activeImport,startImport,clearImport} from '../lib/stores/importStore.js';
  import {audition,previewState,playing,stopPreview} from '../lib/stores/playerStore.js';
  import {toQueueTrack} from '../lib/homelab.js';
  import {importErrorMessage,importActionError} from '../lib/importReviewMessages.js';
  import {importHistoryGroups,importWorkState} from '../lib/importHistory.js';
  import {importCounts,needsImportChoice,canSearchImportAlternatives,canDecideImportItem,reviewImportItems,importItemFailure,importItemTitle,importPhaseLabel} from '../lib/importProgress.js';
  export let onRefresh=()=>{};
  export let onOpenPending=()=>{};
  export let visible=true;
  /** «Importar todo Spotify», the secondary way in, as in the app. */
  export let onImportAll=null;
  // As in the app: with an import waiting, that import is what the screen is for and the form folds away.
  let newOpen=null,showCompleted=false;
  $: formOpen=newOpen??(!groups.pending.length&&!$activeImport);
  $: counts=importCounts($activeImport);
  $: done=$activeImport?!activePending:false;
  const songs=n=>`${n||0} ${n===1?'canción':'canciones'}`;
  let history=[], playlists=[], url='', target='', recoveryTarget='', error='', busy=false, queries={};
  let scroller, reviewSummary, notice='', pendingNotice=false, localFailures={}, mounted=false, loaded=false;
  $: groups=importHistoryGroups(history,$activeImport);
  $: selectedPending=groups.pending.some(job=>job.importId===$activeImport?.importId)?$activeImport.importId:'';
  $: activePending=importWorkState($activeImport).pending;
  $: onlyIndexing=importWorkState($activeImport).onlyIndexing===true;
  $: if(visible&&mounted)void act(load);
  $: currentFailures=localFailures[$activeImport?.importId]||{};
  $: reviewItems=reviewImportItems($activeImport,currentFailures);
  const states={source_unavailable:'Elemento no recuperado de la fuente',pending:'Pendiente',searching:'Buscando',downloading:'Descargando',indexing:'Pendiente de indexación',ready:'Lista',review:'Revisar coincidencia',not_found:'Sin resultados',search_failed:'Búsqueda fallida',download_failed:'Descarga fallida',skipped:'Omitida'};
  const stages={source_partial:'Recuperación parcial de la fuente',acoustic:'Comprobando referencia acústica',playlist:'Obteniendo playlist',library_lookup:'Consultando biblioteca',search:'Buscando candidatos',comparison:'Comparando metadatos',audio_total:'Resolviendo y descargando audio',audio_resolution:'Resolviendo audio',download:'Descargando',processing:'Procesando audio',publication:'Guardando archivo',indexing:'Indexando en biblioteca',playlist_update:'Actualizando playlist',review:'Hay canciones para revisar',complete:'Proceso terminado',paused:'Pausada',interrupted:'Interrumpida: puedes continuar',recovery:'Necesita recuperación'};
  const acousticStates={identity_conflict:'identidad de referencia contradictoria',candidate_audio_unavailable:'audio autorizado del candidato no disponible',not_exact_uncalibrated:'audio distinto; similitud aún sin calibrar',ambiguous:'varios candidatos equivalentes',budget_exhausted:'se alcanzó el límite de tiempo',reference_unavailable:'referencia no disponible o inválida'};
  const reasons={'different recording version':'Versión distinta (directo, remix, cover…)','duration differs':'La duración difiere','duration unverified':'Duración sin verificar','title or artist is not exact enough':'Título o créditos de artistas diferentes','version detail differs':'Los detalles de la versión difieren','conflicting isrc':'ISRC diferente','conflicting recording_mbid':'Identificador de grabación diferente'};
  async function load(){
    const session=getSession();
    const saved=await call('/api/imports');
    if(!mounted||getSession()!==session)return;
    history=saved.imports||[];loaded=true;
    const result=await library('getPlaylists');
    if(!mounted||getSession()!==session)return;
    playlists=(result.playlists?.playlist||[]).filter(p=>p.owner===session?.username);
    // A stopped job is no longer polled, but another device can still finish
    // or delete it. Refresh the selected detail on reopen, not just its label.
    if($activeImport){
      const id=$activeImport.importId;
      try{await select(id);}
      catch(e){
        if(getSession()!==session||!mounted)return;
        if(e.status!==404)throw e;
        history=history.filter(job=>job.importId!==id);clearImport();
      }
    }
    if(!mounted||getSession()!==session)return;
    if(!$activeImport || !importWorkState($activeImport).pending){
      const next=importHistoryGroups(history,$activeImport).pending[0];
      clearImport();
      if(next)await select(next.importId);
    }
  }
  onMount(()=>{mounted=true;if(!visible)void act(load);return()=>{mounted=false;};});
  async function act(work){if(busy)return;busy=true;error='';try{await work();}catch(e){error=importActionError(e);}finally{busy=false;}}
  async function select(id){
    const session=getSession();let job=await importStatus(id);
    if(getSession()!==session||!mounted)return;
    if($activeImport?.importId===id&&($activeImport.revision??-1)>(job.revision??-1))job=$activeImport;
    // Keep a compact, refreshed summary when the active detail is later cleared.
    const {items,failures,...summary}=job;
    history=history.some(entry=>entry.importId===id)?history.map(entry=>entry.importId===id?summary:entry):[summary,...history];
    notice='';pendingNotice=false;activeImport.set(job);startImport(id,job.name,job.total,job);
  }
  let file=null,fileName='',fileInput,completeInput;
  const MAX_FILE=2*1024*1024;
  async function readFile(f){
    if(f.size>MAX_FILE)throw new Error('El archivo supera 2 MB.');
    return await f.text();
  }
  function pick(e){file=e.target.files?.[0]||null;if(file&&!fileName)fileName=file.name.replace(/\.[^.]+$/,'').slice(0,150);}
  async function complete(e){
    const f=e.target.files?.[0];e.target.value='';
    if(f)await act(async()=>{const content=await readFile(f);await decide('refresh_source',null,null,content);});
  }
  async function begin(){
    const job=file
      ?await call('/api/import/file',{method:'POST',body:JSON.stringify({name:fileName.trim()||'Playlist importada',content:await readFile(file),playlistId:target||null})})
      :await call('/api/import/spotify',{method:'POST',body:JSON.stringify({url,playlistId:target||null})});
    file=null;fileName='';if(fileInput)fileInput.value='';
    url='';newOpen=null;startImport(job.importId,job.name,job.total);await load();
  }
  async function decide(action,index=null,source_id=null,content=null){
    if(action==='confirm'||action==='skip')stopPreview();
    const job=$activeImport;
    const session=getSession();
    const item=index==null?null:job.items[index];
    const card=index==null?null:scroller?.querySelector(`[data-review-index="${index}"]`);
    const anchor=card?Math.max(card.getBoundingClientRect().top,scroller.getBoundingClientRect().top+8):null;
    const after=reviewItems.slice(reviewItems.findIndex(row=>row.index===index)+1).map(row=>row.index);
    notice='';pendingNotice=false;
    try{
      const next=await call(`/api/import/${job.importId}/decision`,{method:'POST',body:JSON.stringify({revision:job.revision,itemRevision:item?(item.choiceRevision??0):undefined,action,index,source_id,query:queries[index]||null,content})});
      if(getSession()!==session)return;
      if(index!=null){const failures={...(localFailures[job.importId]||{})};delete failures[index];localFailures={...localFailures,[job.importId]:failures};}
      startImport(next.importId,next.name,next.total,next);onRefresh();
      if(action==='confirm'||action==='skip'){
        pendingNotice=action==='skip'&&next.manualInboxAvailable===true&&next.items[index]?.manualPending===true;
        notice=action==='confirm'?'Elección guardada. Puedes seguir revisando mientras se procesa.':pendingNotice?'Guardada en Pendientes de añadir. Puedes continuar con la importación.':'Canción omitida.';
        await tick();
        const nextRow=after.map(i=>scroller.querySelector(`[data-review-index="${i}"]`)).find(Boolean)
          ||scroller.querySelector('[data-review-index]');
        if(nextRow){nextRow.focus({preventScroll:true});if(anchor!=null)scroller.scrollTop+=nextRow.getBoundingClientRect().top-anchor;}
        else reviewSummary?.focus({preventScroll:true});
      }
    }catch(e){
      if(getSession()!==session)return;
      // A lost response may still have committed the choice. Reconcile before
      // presenting it again, and do not replace the original error if offline.
      try{await select(job.importId);}catch{/* Polling will retry when connectivity returns. */}
      if(index!=null && showFailedDecision($activeImport,job.importId,index)){
        localFailures={...localFailures,[job.importId]:{...(localFailures[job.importId]||{}),[index]:{order:Date.now(),message:importActionError(e)}}};
      }
      throw e;
    }
  }
  function showFailedDecision(current,id,index){return current?.importId===id && reviewImportItems(current).some(row=>row.index===index);}
  async function removeHistory(){
    const job=$activeImport;
    if(!job||job.status==='running'||!confirm('¿Eliminar esta importación del historial? Se perderán sus elecciones y progreso de revisión. Las playlists y los archivos musicales se conservan.'))return;
    await call(`/api/import/${job.importId}`,{method:'DELETE',body:JSON.stringify({revision:job.revision})});
    stopPreview();clearImport();await load();
  }
</script>
<div class="import-review" bind:this={scroller}>
  {#if formOpen}
    <section class="card new">
      <h3>Nueva importación</h3>
      <form on:submit|preventDefault={()=>act(begin)}>
        <label class="field"><span>Enlace de la playlist de Spotify</span>
          <input aria-label="Playlist pública de Spotify" bind:value={url} required={!file} disabled={!!file} inputmode="url" autocomplete="off" placeholder="https://open.spotify.com/playlist/…"></label>
        <p class="hint">Tiene que ser pública. El enlace público puede mostrar solo las primeras 100 canciones.</p>
        <details class="file" open={!!file}><summary>¿Es más larga? Sube el archivo exportado</summary>
          <p class="hint">Exporta la lista completa a CSV con <a href="https://github.com/watsonbox/exportify" target="_blank" rel="noopener noreferrer">Exportify</a> (inicias sesión en Spotify en su página, no aquí). También vale un texto con una línea «Artista - Título» por canción.</p>
          <input class="pick" type="file" aria-label="Archivo exportado de la playlist" accept=".csv,.txt,text/csv,text/plain" bind:this={fileInput} on:change={pick}>
          {#if file}<label class="field"><span>Nombre de la playlist</span><input aria-label="Nombre de la playlist importada" bind:value={fileName} maxlength="150" required></label>{/if}
        </details>
        <label class="field"><span>Destino</span><select aria-label="Destino de importación" bind:value={target}>
          <option value="">Crear una playlist nueva</option>
          {#each playlists as p}<option value={p.id}>Recuperar en «{p.name}»</option>{/each}
        </select></label>
        {#if target}<p class="hint">Se comprobarán las canciones y el orden existentes. Las pendientes se mostrarán para revisión; las ya importadas se conservan.</p>{/if}
        <button class="filled wide" disabled={busy||$activeImport?.status==='running'||(!url.trim()&&!file)}>{target?'Recuperar en esta playlist':'Importar'}</button>
      </form>
      {#if onImportAll}
        <hr>
        <p>¿Quieres traer todas tus playlists de una vez?</p>
        <button class="outlined wide" on:click={onImportAll}>Importar todo Spotify</button>
        <p class="hint">Elige el archivo de Exportify o conecta con Spotify. El progreso aparece después aquí, en Importaciones pendientes.</p>
      {/if}
    </section>
  {:else}
    <button class="outlined wide" on:click={()=>newOpen=true}><i aria-hidden="true" class="ph ph-caret-down"></i> Nueva importación</button>
  {/if}

  <h3 class="section">Importaciones pendientes{#if groups.pending.length}<span class="badge">{groups.pending.length}</span>{/if}</h3>
  {#if groups.pending.length}
    <ul class="rows">{#each groups.pending as job (job.importId)}
      <li><button class="row" class:selected={job.importId===selectedPending} aria-current={job.importId===selectedPending} disabled={busy} on:click={()=>act(()=>select(job.importId))}>
        <span class="icon" aria-hidden="true"><i class="ph-fill ph-music-note"></i></span>
        <span class="txt"><b>{job.name}</b><small>{songs(job.total)} · {importWorkState(job).label}{job.importId===selectedPending?' · Abierta abajo':''}</small></span>
        <i aria-hidden="true" class="ph ph-caret-right go"></i></button></li>
    {/each}</ul>
  {:else if error}<p class="hint">No se pudo comprobar si hay importaciones pendientes.</p>
  {:else if loaded}<p class="hint" role="status">No tienes importaciones pendientes.</p>
  {:else}<p class="hint" role="status">Consultando importaciones…</p>{/if}
  {#if groups.completed.length}
    <button class="text" aria-expanded={showCompleted} on:click={()=>showCompleted=!showCompleted}>
      <i aria-hidden="true" class="ph {showCompleted?'ph-caret-up':'ph-caret-down'}"></i> {showCompleted?'Ocultar':'Ver'} historial ({groups.completed.length})</button>
    {#if showCompleted}<ul class="rows">{#each groups.completed as job (job.importId)}
      <li><button class="row" class:selected={job.importId===$activeImport?.importId} aria-label={`Ver resumen de ${job.name}`} disabled={busy} on:click={()=>act(()=>select(job.importId))}>
        <span class="icon" aria-hidden="true"><i class="ph-fill ph-music-note"></i></span>
        <span class="txt"><b>{job.name}</b><small>{songs(job.total)} · Terminada</small></span>
        <i aria-hidden="true" class="ph ph-caret-right go"></i></button></li>
    {/each}</ul>{/if}
  {/if}
  {#if error}<p role="alert">{error}</p>{/if}
  {#if notice}<p role="status" class="notice">{notice}</p>{/if}
  {#if pendingNotice}<button class="outlined" on:click={onOpenPending}>Abrir Pendientes de añadir</button>{/if}
  {#if $activeImport && !activePending}
    <div class="card job finished" role="status"><div class="job-head"><h4>{$activeImport.name}</h4><span class="state">Terminada</span></div><p>Importación finalizada. No quedan canciones por procesar aquí.</p>
      {#if $activeImport.skipped}<p>Puedes gestionar las canciones omitidas desde «Pendientes de añadir»; no impiden terminar esta importación.</p><button on:click={onOpenPending}>Abrir Pendientes de añadir</button>{/if}
      {#if groups.pending.length}<button disabled={busy} on:click={()=>act(()=>select(groups.pending[0].importId))}>Revisar siguiente importación pendiente</button>{/if}
      <button disabled={busy} on:click={()=>act(removeHistory)}>Eliminar importación del historial</button>
    </div>
  {:else if $activeImport}
    <section class="card job">
    <div class="job-head"><h4>{$activeImport.name}</h4><span class="state" class:running={$activeImport.status==='running'}>{$activeImport.status==='running'?'En curso':'En pausa'}</span></div>
    <div class="bar" aria-hidden="true"><span style:width="{$activeImport.total?counts.processed/$activeImport.total*100:0}%"></span></div>
    <p aria-live="polite" tabindex="-1" bind:this={reviewSummary}>{counts.processed} de {$activeImport.total} procesadas · {importPhaseLabel($activeImport,{...stages,indexing_pending:'Esperando la biblioteca'})}</p>
    <div class="pills">
      {#each [[counts.ready,'listas','ok'],[counts.needsReview,'por revisar','warn'],[counts.errors,'con error','bad'],[counts.inProgress,'en curso',''],[counts.queued,'por procesar',''],[counts.indexing,'esperando la biblioteca',''],[counts.skipped,'omitidas','']] as [n,label,tone]}
        {#if n}<span class="pill {tone}">{n} {label}</span>{/if}
      {/each}
    </div>
    {#if $activeImport.sourceInfo && !$activeImport.sourceInfo.source_complete}
      {@const info=$activeImport.sourceInfo}
      {@const got=info.retrieved ?? $activeImport.total}
      <div class="partial" role="status">
        <strong>{info.source_total==null&&got<99?'Lista sin total confirmado':'Importación parcial'}</strong>
        {#if info.source_total!=null}
          <p>La fuente tiene {info.source_total} canciones y se han recuperado {info.retrieved ?? $activeImport.total}. Faltan {$activeImport.notRetrieved} por recuperar; no son canciones sin coincidencia.</p>
        {:else if got<99}
          <p>Se han recuperado {got} canciones. El enlace público no indica cuántas tiene la lista: si son las mismas que ves en la lista original, está completa.</p>
        {:else}
          <p>Se han recuperado {info.retrieved ?? $activeImport.total} canciones, pero el enlace público no indica cuántas tiene la lista y solo muestra las primeras 100. Si tu lista es más larga, el resto todavía no se ha importado.</p>
        {/if}
        <div class="actions">
          {#if info.metadata_source!=='file'}<button disabled={busy||$activeImport.status==='running'} on:click={()=>act(()=>decide('refresh_source'))}>Volver a consultar la fuente</button>{/if}
          <button disabled={busy||$activeImport.status==='running'} on:click={()=>completeInput.click()}>Completar con el archivo exportado</button>
          <input type="file" hidden aria-label="Archivo exportado para completar la importación" accept=".csv,.txt,text/csv,text/plain" bind:this={completeInput} on:change={complete}>
        </div>
        <p class="muted">Completar conserva las canciones ya importadas y su orden; solo añade las que faltan.</p>
      </div>
    {/if}
    {#if $activeImport.unavailable}<p>{$activeImport.unavailable} posiciones sin metadatos; no son rechazos de coincidencia.</p>{/if}
    {#if $activeImport.indexing}
      <p role="status">{$activeImport.indexing} descargadas y guardadas, esperando la biblioteca; no necesitan elegir otra versión.
        {#if $activeImport.status==='running'}La biblioteca se comprueba al terminar las descargas.
        {:else}Pulsa «{onlyIndexing?'Comprobar biblioteca':'Reevaluar pendientes y continuar'}» para consultar de nuevo la biblioteca sin repetir estas descargas.{/if}
      </p>
    {/if}
    {#if $activeImport.connectionError}<p role="status">Conexión interrumpida. El progreso está guardado; reconectando…</p>{/if}
    {#if $activeImport.error}<p role="alert">{importErrorMessage($activeImport.error)}</p>{/if}
    {#if $activeImport.error==='playlist_missing'}
      <button disabled={busy||$activeImport.status==='running'} on:click={()=>act(()=>decide('create_new'))}>Crear nueva playlist con el progreso guardado</button>
    {/if}
    {#if $activeImport.error && (!$activeImport.playlistId || $activeImport.error==='playlist_missing')}
      <label>Vincular una playlist existente con las mismas canciones<select bind:value={recoveryTarget}><option value="">Selecciona una playlist</option>{#each playlists as p}<option value={p.id}>{p.name}</option>{/each}</select></label>
      <button disabled={busy||!recoveryTarget} on:click={()=>act(async()=>{await call(`/api/import/${$activeImport.importId}/attach`,{method:'POST',body:JSON.stringify({revision:$activeImport.revision,playlistId:recoveryTarget})});await select($activeImport.importId);})}>Vincular sin duplicar</button>
    {/if}
    <div class="actions">
      <button disabled={busy} on:click={()=>act(()=>select($activeImport.importId))}>Actualizar</button>
      <button disabled={busy||$activeImport.status==='running'} on:click={()=>act(removeHistory)}>Eliminar importación del historial</button>
      {#if $activeImport.status==='running'}
        <button disabled={busy} on:click={()=>act(async()=>{await call(`/api/import/${$activeImport.importId}/cancel`,{method:'POST'});await select($activeImport.importId);})}>Pausar</button>
      {:else}<button disabled={busy} on:click={()=>act(()=>decide('resume'))} title={onlyIndexing?'Consulta de nuevo la biblioteca sin repetir las descargas':'Vuelve a juzgar con las reglas actuales las canciones pendientes de revisar y continúa la importación'}>{onlyIndexing?'Comprobar biblioteca':'Reevaluar pendientes y continuar'}</button>{/if}
    </div>
    </section>
    {#if reviewItems.length}<h3 class="section">Canciones que necesitan tu decisión<span class="badge">{reviewItems.length}</span></h3>
    <p class="hint">Escucha y compara antes de confirmar. Los metadatos no garantizan que sea la misma grabación.</p>{/if}
    {#each reviewItems as {item,index:i} (i)}
        <article class="music-card" data-review-index={i} tabindex="-1" aria-labelledby={`import-row-${i}`}>
<strong id={`import-row-${i}`}>{i+1}. {importItemTitle(item)}</strong><p>{item.track.artist} · {Math.round(item.track.duration||0)} s</p>
          <p>{states[item.state]||item.state}{item.state==='downloading'?` · ${stages[item.stage]||''}`:''}</p>
          {#if currentFailures[i]}<p role="alert">{currentFailures[i].message}</p>
          {:else if importItemFailure(item)}<p role="status">{importItemFailure(item)}</p>{/if}
          {#if item.selected}<p>Elegida: {item.selected.artist} — {item.selected.title}</p>{/if}
          {#if canSearchImportAlternatives(item)}
          {#if !needsImportChoice(item)}<p class="muted">Puedes reintentar o buscar otra versión si lo necesitas.</p>{/if}
          {#if item.acoustic && !item.acoustic.selected}<p class="muted">{item.acoustic.status==='no_reference'?'Sin referencia acústica autorizada e identificada; no se ha comparado audio.':`Comparación acústica: ${acousticStates[item.acoustic.status]||'evidencia insuficiente'}. No se ha confirmado la grabación.`}</p>{/if}
          {#if item.comparison_reason==='multiple_compatible_sources'}<p class="muted">Varias fuentes coinciden en los metadatos. No se ha confirmado cuál es la misma grabación; elige la que prefieras.</p>{/if}
          {#each item.candidates as c (c.track.source_id)}
            <div class="candidate">
              <button class="candidate-art" aria-label={`Preescuchar ${c.track.title}`} on:click={()=>audition({...toQueueTrack(c.track),_previewThumb:`https://i.ytimg.com/vi/${c.track.source_id}/mqdefault.jpg`})}>
                <img src={`https://i.ytimg.com/vi/${c.track.source_id}/mqdefault.jpg`} alt="" loading="lazy" referrerpolicy="no-referrer" on:error={e=>e.currentTarget.style.visibility='hidden'}>
                <span>{$previewState?.track?._musicTrack?.source_id===c.track.source_id && $playing?'Ⅱ':'▶'}</span>
              </button>
              <div class="candidate-info"><p>{c.track.title}<br>{c.track.artist}<br><small>{c.track.album} · {c.track.duration?`${Math.round(c.track.duration)} s`:'Duración desconocida'}</small></p>
              <p>{c.reasons.length?c.reasons.map(r=>reasons[r]||r).join(' · '):'Metadatos compatibles; revisa la grabación'}</p></div>
              <button class="choose-version" aria-label={`Elegir esta versión: ${c.track.title}`} disabled={busy||!canDecideImportItem($activeImport,item)} on:click={()=>act(()=>decide('confirm',i,c.track.source_id))}>+</button>
            </div>
          {/each}
          <form on:submit|preventDefault={()=>act(()=>decide('search',i))}>
            <label>Buscar otra opción<input aria-label={`Buscar otra opción para ${item.track.title}`} bind:value={queries[i]} placeholder={`${item.track.artist} ${item.track.title}`}></label>
            <button disabled={busy||!canDecideImportItem($activeImport,item)}>Buscar candidatos</button>
          </form>
          {/if}
          <div class="actions">{#if item.state!=='indexing'}<button disabled={busy||!canDecideImportItem($activeImport,item)} on:click={()=>act(()=>decide('skip',i))}>{needsImportChoice(item)?'Ninguna coincide':'Omitir canción'}</button>{/if}<button disabled={busy||!canDecideImportItem($activeImport,item)} on:click={()=>act(()=>decide('retry',i))}>Reintentar</button></div>
        </article>
    {/each}
  {/if}
  <PreviewControls />
</div>
<style>
  .import-review{min-width:0;display:flex;flex-direction:column;gap:10px}
  h3,h4{font-weight:600;color:#fff}
  h3{font-size:1.05rem}
  .section{display:flex;align-items:center;gap:8px;margin-top:6px}
  .badge{font-size:.75rem;font-weight:700;color:var(--color-armonia-accent);background:#c4a3ff24;border-radius:99px;padding:2px 8px}
  p{margin:0;font-size:.88rem;line-height:1.4}
  .hint{color:var(--color-armonia-muted);font-size:.82rem}
  .notice{color:var(--color-armonia-accent)}
  [role=alert]{color:#fca5a5}
  .card{background:#ffffff0a;border-radius:14px;padding:14px;display:flex;flex-direction:column;gap:10px}
  .new form{display:flex;flex-direction:column;gap:10px}
  .field{display:flex;flex-direction:column;gap:4px;font-size:.8rem;color:var(--color-armonia-muted)}
  .field input,.field select{width:100%;padding:12px;background:#ffffff0d;border:1px solid #ffffff38;border-radius:8px;color:#fff;font-size:.95rem}
  .field input:focus,.field select:focus{outline:2px solid var(--color-armonia-accent);border-color:transparent}
  .field option{background:#1f1c26}
  .file summary{cursor:pointer;font-size:.85rem;color:var(--color-armonia-accent);font-weight:600;padding:2px 0}
  .file[open]{display:flex;flex-direction:column;gap:8px}
  .file a{text-decoration:underline}
  .pick{font-size:.85rem;max-width:100%}
  hr{border:0;border-top:1px solid #ffffff14;margin:4px 0}
  .filled,.outlined,.text{display:flex;align-items:center;justify-content:center;gap:6px;border-radius:99px;font-weight:600;font-size:.92rem}
  .filled{background:var(--color-armonia-accent);color:#16121d;padding:12px 18px}
  .outlined{border:1px solid #ffffff40;padding:11px 18px;color:var(--color-armonia-accent)}
  .text{justify-content:flex-start;padding:6px 4px;color:var(--color-armonia-accent)}
  .wide{width:100%}
  .filled:disabled,.outlined:disabled{opacity:.45}
  .rows{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:6px}
  .row{width:100%;display:flex;align-items:center;gap:12px;padding:10px 12px;border-radius:12px;background:#ffffff0a;text-align:left}
  .row.selected{background:#c4a3ff24}
  .row:disabled{opacity:.6}
  .icon{width:40px;height:40px;flex:none;display:grid;place-items:center;border-radius:8px;background:#ffffff14;color:var(--color-armonia-accent);font-size:1.2rem}
  .txt{flex:1;min-width:0;display:flex;flex-direction:column}
  .txt b{font-weight:600;font-size:.92rem;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .txt small{color:var(--color-armonia-muted);font-size:.8rem}
  .go{color:var(--color-armonia-muted)}
  .job-head{display:flex;align-items:flex-start;gap:8px}
  .job-head h4{flex:1;min-width:0;font-size:1.25rem;overflow-wrap:anywhere}
  .state{font-size:.78rem;font-weight:600;color:var(--color-armonia-muted);padding-top:5px}
  .state.running{color:var(--color-armonia-accent)}
  .bar{height:6px;border-radius:3px;background:#ffffff14;overflow:hidden}
  .bar span{display:block;height:100%;background:var(--color-armonia-accent)}
  .pills{display:flex;flex-wrap:wrap;gap:6px}
  .pill{font-size:.8rem;font-weight:600;padding:4px 10px;border-radius:99px;background:#ffffff14;color:#e9e3f2}
  .pill.ok{color:var(--color-armonia-accent);background:#c4a3ff1f}
  .pill.warn{color:#ffc46b;background:#ffc46b1f}
  .pill.bad{color:#ffb4ab;background:#ffb4ab1f}
  .partial{border:1px solid #a78bfa66;background:#a78bfa14;border-radius:10px;padding:.75rem}.partial p{margin:.35rem 0}
  .actions{display:flex;flex-wrap:wrap;gap:6px}
  :where(.job,.music-card,.partial) button:not(.candidate-art){padding:.55rem .9rem;border:1px solid #ffffff40;border-radius:99px;font-size:.85rem;font-weight:600}
  :where(.job,.music-card,.partial) button:disabled{opacity:.45}
  :where(.job,.music-card) label{display:block;margin:.4rem 0;font-size:.82rem;color:var(--color-armonia-muted)}
  :where(.job,.music-card) input,.job select{width:100%;padding:.6rem;background:#ffffff0d;border:1px solid #ffffff38;border-radius:8px;color:#fff;margin-top:4px}
  .music-card{display:flex;flex-direction:column;gap:6px;background:#ffffff0a;border-radius:14px;padding:14px}
  .candidate{display:flex;align-items:center;gap:.75rem;padding:.6rem 0;border-bottom:1px solid #ffffff1a}.candidate-info{flex:1;min-width:0}.candidate-art{position:relative;width:64px;height:64px;flex-shrink:0;padding:0;overflow:hidden;border-radius:8px}.candidate-art img{width:100%;height:100%;object-fit:cover}.candidate-art span{position:absolute;inset:0;display:grid;place-items:center;background:#0005;font-size:1.6rem}.choose-version{font-size:1.7rem;min-width:48px;min-height:48px}
</style>
