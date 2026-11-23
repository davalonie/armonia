<script>
  import {onMount} from 'svelte';
  import {getSession} from '../lib/api.js';
  import {currentView,showView} from '../lib/stores/viewStore.js';
  import {beginLogin,completeLogin,readLibrary,redirectUri} from '../lib/spotifyLogin.js';
  import {loadBatch,batchStatus,loadConfig,saveConfig,startBatch,resumeBatch,pauseBatch,removeFromBatch,forgetBatch,proposeFromSpotify,
    proposeFromArchive,validateArchive,batchError,noteLabel,importable,playlistProgress,pauseReason} from '../lib/importBatch.js';

  let batch=null, loading=true, busy='', error='', reading='', unreadable=[], spotifyUser='';
  let clientId='', fixed=false, editingId=false, draftId='';
  let chosen={}, names={}, alive=true, timer=null, epoch=0;

  $: selected=batch?.status==='preview'?batch.playlists.filter(p=>chosen[p.index]&&importable(p)):[];
  $: songs=selected.reduce((sum,p)=>sum+p.total,0);
  $: finished=batch?.playlists.filter(p=>p.import&&p.import.status!=='running'&&p.state!=='waiting').length||0;
  $: queued=batch?.playlists.filter(p=>p.state!=='skipped').length||0;
  $: review=batch?.playlists.reduce((sum,p)=>sum+(p.import?.review||0),0)||0;

  function show(next) {
    batch=next;
    if(next?.status==='preview'){
      chosen=Object.fromEntries(next.playlists.map(p=>[p.index,importable(p)&&!p.existing]));
      names=Object.fromEntries(next.playlists.map(p=>[p.index,p.name]));
    }
    schedule();
  }
  function schedule() {
    clearTimeout(timer);
    if(!alive||batch?.status!=='running')return;
    const mine=epoch, session=getSession();
    timer=setTimeout(async()=>{
      try{const next=await batchStatus(batch.id);if(alive&&mine===epoch&&getSession()===session)batch=next;}
      catch(e){if(e.status===404&&mine===epoch)batch=null;}
      if(mine===epoch)schedule();
    },3000);
  }
  async function run(label,work) {
    if(busy)return;
    busy=label;error='';epoch++;clearTimeout(timer);
    try{await work();}catch(e){if(alive)error=batchError(e);}
    finally{busy='';schedule();}
  }

  async function open() {
    loading=true;error='';
    const session=getSession();
    try {
      const config=await loadConfig();
      if(!alive||getSession()!==session)return;
      clientId=config.spotifyClientId||'';fixed=!!config.fixed;draftId=clientId;
      let token=null;
      try{token=await completeLogin();}
      catch(e){error=e.message;}
      // The one-time code must not stay in the address bar, the history or a reload.
      if(/[?&](code|error)=/.test(location.search))history.replaceState(null,'',location.pathname);
      if(token){await fromSpotify(token);return;}
      show((await loadBatch()).batch);
    } catch(e){if(alive)error=batchError(e);}
    finally{if(alive){loading=false;reading='';}}
  }
  async function fromSpotify(token) {
    reading='Leyendo tu biblioteca de Spotify…';
    const library=await readLibrary(token,{onProgress:name=>{if(alive)reading=`Leyendo «${name}»…`;}});
    if(!alive)return;
    spotifyUser=library.user;unreadable=library.unreadable;
    if(!library.playlists.length){error='Spotify no ha entregado ninguna lista propia, cancion guardada ni album.';show((await loadBatch()).batch);return;}
    reading='Preparando la lista…';
    show(await proposeFromSpotify(library.playlists));
  }
  onMount(()=>{
    alive=true;
    const unsubscribe=currentView.subscribe(view=>{if(view==='import-all')void open();else clearTimeout(timer);});
    return ()=>{alive=false;epoch++;clearTimeout(timer);unsubscribe();};
  });

  const connect=()=>run('spotify',async()=>{location.assign(await beginLogin(clientId));});
  const keepId=()=>run('config',async()=>{const saved=await saveConfig(draftId.trim());clientId=saved.spotifyClientId;editingId=false;});
  function pickArchive(event) {
    const file=event.target.files?.[0];event.target.value='';
    if(!file)return;
    try{validateArchive(file);}catch(e){error=e.message;return;}
    unreadable=[];spotifyUser='';
    void run('zip',async()=>show(await proposeFromArchive(file)));
  }
  const begin=()=>run('start',async()=>show(await startBatch(batch.id,selected.map(p=>p.index),
    Object.fromEntries(selected.filter(p=>names[p.index]?.trim()&&names[p.index].trim()!==p.name).map(p=>[p.index,names[p.index].trim()])))));
  const resume=()=>run('resume',async()=>show(await resumeBatch(batch.id)));
  const pause=()=>run('pause',async()=>show(await pauseBatch(batch.id)));
  const drop=p=>run('remove',async()=>show(await removeFromBatch(batch.id,p.index)));
  const discard=()=>run('forget',async()=>{await forgetBatch(batch.id);unreadable=[];show(null);});
  function all(value){chosen=Object.fromEntries(batch.playlists.map(p=>[p.index,value&&importable(p)]));}
</script>

<section class="import-all music-page">
  <button class="back" on:click={()=>showView('library')}>← Biblioteca</button>
  <h1>Importar todo Spotify</h1>
  {#if error}<p role="alert">{error}</p>{/if}

  {#if loading||reading}
    <p role="status" class="status">{reading||'Cargando…'}</p>
  {:else if !batch}
    <p class="intro">Trae todas tus listas de una vez. Cada una se importa como siempre: lo dudoso queda para revisar y lo que no exista va a «Pendientes de añadir».</p>
    <div class="sources">
      <article>
        <h2>Con el archivo de Exportify</h2>
        <p>Incluye tambien las listas de otras personas que sigues y no depende de tu suscripcion.</p>
        <ol>
          <li>Abre la web de <a href="https://github.com/watsonbox/exportify" target="_blank" rel="noopener noreferrer">Exportify</a> (enlazada en su pagina) e inicia sesion con Spotify.</li>
          <li>Pulsa «Exportar todo»: se descarga un archivo ZIP.</li>
          <li>Eligelo aqui.</li>
        </ol>
        <label class="file">Archivo ZIP de Exportify<input type="file" accept=".zip,application/zip" disabled={!!busy} on:change={pickArchive} /></label>
        {#if busy==='zip'}<p role="status">Leyendo el archivo…</p>{/if}
      </article>
      <article>
        <h2>Iniciando sesion en Spotify</h2>
        <p>Lee tus listas propias o colaborativas, tus canciones guardadas y tus albumes. Spotify no entrega a una aplicacion personal las listas de otras personas, y exige que su dueño tenga Premium activo.</p>
        {#if clientId&&!editingId}
          <button class="primary" disabled={!!busy} on:click={connect}>Conectar con Spotify</button>
          {#if !fixed}<button class="link" on:click={()=>{editingId=true;draftId=clientId;}}>Cambiar identificador</button>{/if}
          <p class="hint">El inicio de sesion ocurre en la pagina de Spotify. Armonia no recibe tu contraseña ni guarda el acceso.</p>
        {:else}
          <label class="field">Client ID de tu aplicacion de Spotify
            <input bind:value={draftId} autocomplete="off" spellcheck="false" placeholder="32 letras y numeros" /></label>
          <p class="hint">Se crea en developer.spotify.com con esta direccion de retorno: <code>{redirectUri()}</code>. No es un secreto; no escribas aqui el «Client secret».</p>
          <button class="primary" disabled={!!busy||!/^[0-9a-f]{32}$/.test(draftId.trim())} on:click={keepId}>Guardar</button>
          {#if clientId}<button class="link" on:click={()=>editingId=false}>Cancelar</button>{/if}
        {/if}
      </article>
    </div>
  {:else if batch.status==='preview'}
    <p class="intro">{batch.source==='spotify'?`Listas leidas de Spotify${spotifyUser?` (${spotifyUser})`:''}.`:'Listas encontradas en el archivo.'} Elige cuales importar; puedes cambiarles el nombre.</p>
    <div class="bar"><button on:click={()=>all(true)}>Marcar todas</button><button on:click={()=>all(false)}>Ninguna</button></div>
    <ul class="rows">
      {#each batch.playlists as p (p.index)}
        <li class:off={!importable(p)}>
          <input type="checkbox" aria-label={`Importar ${p.name}`} bind:checked={chosen[p.index]} disabled={!importable(p)||!!busy} />
          <input class="name" aria-label={`Nombre para ${p.name}`} bind:value={names[p.index]} maxlength="150" disabled={!importable(p)||!!busy} />
          <span class="count">{p.total} {p.total===1?'cancion':'canciones'}</span>
          <span class="note">{[noteLabel(p.note),p.existing?'Ya importada antes':''].filter(Boolean).join(' · ')}</span>
        </li>
      {/each}
    </ul>
    {#if unreadable.length}
      <details class="unreadable"><summary>{unreadable.length} {unreadable.length===1?'lista no se puede leer':'listas no se pueden leer'} con el inicio de sesion</summary>
        <p>Son de otras personas o de Spotify. Para traerlas usa el archivo de Exportify.</p>
        <ul>{#each unreadable as u}<li>{u.name}{u.owner?` · ${u.owner}`:''}{u.total!=null?` · ${u.total} canciones`:''}</li>{/each}</ul>
      </details>
    {/if}
    <div class="actions">
      <button class="primary" disabled={!!busy||!selected.length} on:click={begin}>Importar {selected.length} {selected.length===1?'playlist':'playlists'} ({songs} canciones)</button>
      <button disabled={!!busy} on:click={discard}>Descartar</button>
    </div>
    <p class="hint">Se importan una detras de otra. Puedes cerrar esta pagina: el servidor continua.</p>
  {:else}
    <p class="status" role="status">
      {#if batch.status==='running'}Importando: {finished} de {queued} playlists terminadas.
      {:else if batch.status==='paused'}{pauseReason(batch.reason)}
      {:else}Terminado: {finished} de {queued} playlists importadas{review?`, ${review} canciones por revisar`:''}.{/if}
    </p>
    <ul class="rows progress">
      {#each batch.playlists.filter(p=>p.state!=='skipped') as p (p.index)}
        {@const state=playlistProgress(p)}
        <li><span class="title">{p.name}</span><span class="count">{p.total} canciones</span><span class={`note ${state.tone}`}>{state.label}</span>
          {#if p.state==='waiting'}<button class="link drop" disabled={!!busy} on:click={()=>drop(p)} aria-label={`Quitar ${p.name} de la cola`}>Quitar de la cola</button>{/if}</li>
      {/each}
    </ul>
    <div class="actions">
      {#if batch.status==='running'}<button disabled={!!busy} on:click={pause}>Pausar la cola</button>{/if}
      {#if batch.status==='paused'}<button class="primary" disabled={!!busy} on:click={resume}>Continuar</button>{/if}
      <button on:click={()=>showView('library')}>Ver importaciones y revisar</button>
      {#if batch.status!=='running'}<button disabled={!!busy} on:click={discard}>{batch.status==='done'?'Importar otras listas':'Olvidar esta cola'}</button>{/if}
    </div>
    {#if batch.status!=='done'}<p class="hint">Lo dudoso de cada playlist se revisa en Biblioteca → Playlists → Importar, sin esperar a que acabe la cola.</p>{/if}
  {/if}
</section>

<style>
  .import-all{max-width:1000px;margin:0 auto;padding:20px 16px 40px}.back{margin-bottom:14px;color:var(--color-armonia-muted)}
  h1{font-size:1.8rem;font-weight:750;margin-bottom:10px}h2{font-size:1.1rem;font-weight:650;margin-bottom:8px}
  .intro,.hint,.sources p{color:var(--color-armonia-muted);max-width:75ch}.hint{font-size:.85rem;margin-top:10px}.status{margin:14px 0;font-weight:600}
  .sources{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));margin-top:18px}
  article{padding:18px;background:#ffffff08;border:1px solid #ffffff1a;border-radius:14px;min-width:0}
  ol{margin:10px 0 12px 20px;list-style:decimal;color:var(--color-armonia-muted)}a{color:var(--color-armonia-accent);text-decoration:underline}
  .file,.field{display:flex;flex-direction:column;gap:8px;margin:12px 0;font-size:.9rem}.file input{max-width:100%;min-width:0}
  .field input,.name{background:#ffffff0d;padding:9px 11px;border-radius:9px;border:1px solid #ffffff30;color:inherit;min-width:0}
  code{overflow-wrap:anywhere;background:#ffffff14;padding:1px 5px;border-radius:5px}
  button{border:1px solid #ffffff35;padding:9px 13px;border-radius:9px}button.primary{background:var(--color-armonia-accent);color:#121015;font-weight:650;border-color:transparent}
  button.link{border:0;color:var(--color-armonia-muted);text-decoration:underline}button:disabled{opacity:.45}
  .bar,.actions{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}
  .rows{display:grid;gap:6px}.rows li{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:6px 12px;align-items:center;padding:10px 12px;background:#ffffff08;border:1px solid #ffffff14;border-radius:11px}
  .rows.progress li{grid-template-columns:minmax(0,1fr) auto}.rows li.off{opacity:.55}.title{overflow-wrap:anywhere;font-weight:600;min-width:0}.drop{grid-column:1/-1;justify-self:start;padding:0}
  .count{color:var(--color-armonia-muted);font-size:.85rem;white-space:nowrap}.note{grid-column:1/-1;font-size:.85rem;color:var(--color-armonia-muted)}.note:empty{display:none}
  .note.active{color:var(--color-armonia-accent)}.note.done{color:var(--color-armonia-success,#86efac)}.note.review{color:#fcd34d}.note.error{color:#fca5a5}
  .unreadable{margin:14px 0;color:var(--color-armonia-muted)}.unreadable ul{margin:8px 0 0 18px;list-style:disc}
  [role=alert]{color:#fca5a5;margin:10px 0}
</style>
