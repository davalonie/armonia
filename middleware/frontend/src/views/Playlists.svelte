<script>
  import {pullRefresh} from '../lib/pullRefresh.js';
  import {mobile,mobileImport} from '../lib/native.js';
  import PhonePlaylist from '../components/PhonePlaylist.svelte';
  import {onMount} from 'svelte';
  import {currentView,showView} from '../lib/stores/viewStore.js';
  import {stopPreview} from '../lib/stores/playerStore.js';
  import {api} from '../lib/homelab.js';
  import MixedPlaylists from './MixedPlaylists.svelte';
  import { call, getSession, library as libApi, coverArtUrl } from '../lib/api.js';
  import Cover from '../components/Cover.svelte';
  import {createEventDispatcher} from 'svelte';
  const dispatch=createEventDispatcher();
  import PlaylistSearch from '../components/PlaylistSearch.svelte';
  import PhoneAddSongs from '../components/PhoneAddSongs.svelte';
  import {appendLocal,replaceLocal} from '../lib/playlistEdits.js';
  import {showToast} from '../lib/stores/toastStore.js';
  import ImportReview from '../components/ImportReview.svelte';
  import TrackList from '../components/TrackList.svelte';
  import { showContextMenu } from '../lib/stores/contextMenuStore.js';
  import { activeImport } from '../lib/stores/importStore.js';
  import {importWorkState} from '../lib/importHistory.js';

  let stack = [{ type: 'playlists', label: 'Playlists' }];
  let playlists = [];
  let playlistFilter = '';
  let songs = [];
  let detailCover = null;
  let loading = true;
  let error = '';
  let stale = false, loadGeneration = 0;

  // Dialogs
  let createOpen = false;
  let createName = '';
  let createDialogEl;
  let renameOpen = false;
  let renameId = '';
  let renameCurrentName = '';
  let renameName = '';
  let renameDialogEl;
  let songPickerOpen = false;
  let songPickerPlaylistId = '';
  let songPickerPlaylistName = '';
  let spDialogEl;

  // Import playlist
  let importOpen = false;
  let importDialogEl;
  let reloadedFor = null;      // import id we've already refreshed playlists for

  // When the tracked import finishes, refresh the playlist list once.
  $: if ($activeImport?.status === 'done' && reloadedFor !== $activeImport.importId) {
    reloadedFor = $activeImport.importId;
    loadPlaylists();
  }

  $: top = stack[stack.length - 1];
  $: dispatch('detail',stack.length>1);
  $: filteredPlaylists = playlistFilter
    ? playlists.filter(p => p.name.toLowerCase().includes(playlistFilter.toLowerCase()))
    : playlists;
  let playlistSort='recent';
  $: sortedPlaylists=[...filteredPlaylists].sort((a,b)=>(a.kind==='mixed')-(b.kind==='mixed')||(playlistSort==='name'?a.name.localeCompare(b.name,'es'):playlistSort==='size'?(b.songCount||0)-(a.songCount||0):String(b.changed||b.updated||'').localeCompare(String(a.changed||a.updated||''))));
  $: top, loadCurrent();

  async function loadCurrent() {
    const generation = ++loadGeneration;
    loading = true; error = ''; stale = false;
    try {
      if (top.type === 'playlists') await loadPlaylists();
      else if (top.type === 'playlist') await loadPlaylist(top.id);
    } catch (e) { if (generation === loadGeneration) error = e.message; }
    finally { if (generation === loadGeneration) loading = false; }
  }

  async function loadPlaylists() {
    const generation = loadGeneration;
    function publish(local, mixed) {
      if (generation !== loadGeneration || top.type !== 'playlists') return;
      playlists=[...local.map(p=>({...p,kind:'local'})),...mixed.map(p=>({...p,kind:'mixed',songCount:p.item_count,changed:new Date(p.updated*1000).toISOString()}))];
    }
    if (!mobile) {
      const [r,m] = await Promise.all([libApi('getPlaylists'),api.playlists()]);
      publish(r.playlists?.playlist || [],m.playlists);
      return;
    }
    const cached = (await mobile.playlists({cached:true})).playlists;
    if (cached && generation === loadGeneration) { publish(cached,[]); loading=false; }
    const mixes = api.playlists().then(r=>r.playlists).catch(()=>[]);
    try {
      const {playlists:local} = await mobile.playlists({});
      publish(local,await mixes);
      if (generation === loadGeneration) { stale=false; error=''; }
    } catch(e) {
      if (!cached) throw e;
      if (generation === loadGeneration) stale=true;
    }
  }

  async function loadPlaylist(id) {
    const generation = loadGeneration;
    function publish(list) {
      if (generation !== loadGeneration || top.id !== id) return;
      detailCover=list.coverArt;
      songs=list.entry || [];
    }
    if (!mobile) { publish((await libApi('getPlaylist',{id})).playlist); return; }
    const cached = (await mobile.playlists({id,cached:true})).playlist;
    if (cached && generation === loadGeneration) { publish(cached); loading=false; }
    try { publish((await mobile.playlists({id})).playlist); if (generation===loadGeneration) stale=false; }
    catch(e) { if (!cached) throw e; if (generation===loadGeneration) stale=true; }
  }

  onMount(()=>{let first=true;return currentView.subscribe(view=>{if(first){first=false;return;}if(['library','playlists'].includes(view)&&top?.type==='playlists')void loadPlaylists().catch(e=>error=e.message);});});

  function push(item) { stack = [...stack, item]; }
  function goTo(idx) { stack = stack.slice(0, idx + 1); }

  let picker, artworkTarget;
  async function chooseCover(p){
    if (mobile) {
      try { if (!(await mobileImport.pickCover({kind:p.kind,id:p.id})).cancelled) await loadPlaylists(); }
      catch(e){ showToast(e.message,'error'); }
      return;
    }
    artworkTarget=p;picker.value='';picker.click();
  }
  async function uploadCover(){
    const file=picker.files?.[0], p=artworkTarget;
    if(!file||!p)return;
    if(file.size>8*1024*1024){showToast('La imagen debe ocupar como maximo 8 MiB.','error');return;}
    try{
      await call(`/api/playlist-covers/${p.kind}/${encodeURIComponent(p.id)}`,{method:'PUT',body:file,headers:{'Content-Type':file.type||'application/octet-stream'}});
      await loadPlaylists();
    }catch(e){showToast(e.detail||e.message,'error');}
  }

  function openDots(e, p) {
    e.stopPropagation();
    if(p.kind==='mixed'){
      showContextMenu(e.currentTarget,[{label:'Cambiar portada',icon:'ph ph-image',action:()=>chooseCover(p)}]);return;
    }
    showContextMenu(e.currentTarget, [
      ...(p.owner===getSession()?.username?[{label:"Cambiar portada",icon:"ph ph-image",action:()=>chooseCover(p)}]:[]),
      {
        label: 'Añadir canciones', icon: 'ph ph-plus-circle',
        action: () => openSongPicker(p.id, p.name),
      },
      {
        label: 'Cambiar nombre', icon: 'ph ph-pencil',
        action: () => { renameId = p.id; renameCurrentName = p.name; renameName = p.name; renameOpen = true; renameDialogEl?.showModal(); },
      },
      null,
      {
        label: 'Eliminar playlist', icon: 'ph ph-trash', danger: true,
        action: async () => {
          if (!confirm(`¿Eliminar la playlist «${p.name}»? Las canciones siguen en tu biblioteca.`)) return;
          await libApi('deletePlaylist', { id: p.id });
          await loadPlaylists();
        },
      },
    ]);
  }

  async function createPlaylist() {
    const name = createName.trim();
    if (!name) return;
    await libApi('createPlaylist', { name });
    createDialogEl?.close();
    createOpen = false;
    createName = '';
    await loadPlaylists();
  }

  async function renamePlaylist() {
    const name = renameName.trim();
    if (!name || name === renameCurrentName) { renameDialogEl?.close(); renameOpen = false; return; }
    await libApi('updatePlaylist', { playlistId: renameId, name });
    renameDialogEl?.close();
    renameOpen = false;
    await loadPlaylists();
  }

  async function openSongPicker(plId, plName) {
    if(mobile){ phoneAdder={id:plId,name:plName}; return; }
    songPickerPlaylistId = plId;
    songPickerPlaylistName = plName;
    songPickerOpen = true;
    spDialogEl?.showModal();
  }

  // The phone editor saves each song on its own; the lists are read again when it closes.
  let phoneAdder=null;
  async function phoneAdderClosed(){
    const plId=phoneAdder?.id;phoneAdder=null;
    if(top.id===plId) await loadPlaylist(plId); else await loadPlaylists();
  }

  async function addLocal(tracks){
    const result=await appendLocal(songPickerPlaylistId,tracks.map(t=>t.source_id));
    showToast(`${result.added} añadidas · ${result.duplicates} ya estaban`);
    if(top.type==='playlist')await loadPlaylist(top.id);
  }
  async function moveSong(index,delta){
    const before=songs.map(s=>s.id), after=[...before];
    [after[index],after[index+delta]]=[after[index+delta],after[index]];
    try{await replaceLocal(top.id,before,after);await loadPlaylist(top.id);}catch(e){error=e.message;}
  }

  // Called from Biblioteca's «Nueva playlist» and «Importar playlist».
  export function openCreate(){createName='';createOpen=true;createDialogEl?.showModal();}
  export function openImport(){if(mobile){showView('import-review');return;}importOpen=true;importDialogEl?.showModal();}
  let mixedDialogEl,mixedName='',mixedError='';
  function openCreateMixed(){mixedName='';mixedError='';mixedDialogEl?.showModal();}
  async function createMixed(){
    const name=mixedName.trim();if(!name)return;
    try{const made=await api.save({name,revision:0,items:[]});mixedDialogEl?.close();await loadPlaylists();push({type:'mixed',id:made.id,label:made.name});}
    catch(e){mixedError=e.message;}
  }
  function hideImport(){importOpen=false;importDialogEl?.close();}
  function reopenImport(){openImport();}

</script>

<input hidden type="file" accept="image/jpeg,image/png,image/webp" bind:this={picker} on:change={uploadCover}>
<div use:pullRefresh={loadCurrent} class="playlist-pane w-full max-w-5xl mx-auto p-4 md:p-8" class:drilled={mobile && stack.length>1}>

  <!-- Breadcrumb -->
  {#if mobile && top.type==='mixed'}<button class="phone-back" data-phone-back aria-label="Volver" on:click={()=>goTo(0)}><i class="ph ph-arrow-left"></i></button>
  {:else if !mobile && stack.length > 1}
    <div class="flex items-center gap-2 text-sm text-armonia-muted mb-6 flex-wrap">
      {#each stack as crumb, i}
        {#if i < stack.length - 1}
          <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
          <span class="cursor-pointer hover:text-armonia-text transition-colors" on:click={() => goTo(i)} on:keydown={e=>{if(e.key==='Enter')goTo(i);}} role="link" tabindex="0">{crumb.label}</span>
          <i class="ph ph-caret-right text-xs"></i>
        {:else}
          <span class="text-armonia-text font-medium">{crumb.label}</span>
        {/if}
      {/each}
    </div>
  {/if}

  {#if stale}<p role="status" class="text-sm text-armonia-muted">Copia guardada en el teléfono <button class="p-2" on:click={loadCurrent}>Actualizar</button></p>{/if}
  {#if loading}
    <div class="flex items-center justify-center py-20 opacity-50">
      <i class="ph ph-circle-notch text-4xl animate-spin-slow"></i>
    </div>
  {:else if error}
    <div class="flex flex-col items-center justify-center py-20 text-red-400">
      <i class="ph ph-warning-circle text-5xl mb-4"></i><p>{error}</p><button class="p-3" on:click={loadCurrent}>Reintentar</button>
    </div>
  {:else if top.type === 'playlists'}
    <div class="toolbar">
      <label class="filter"><i aria-hidden="true" class="ph ph-magnifying-glass"></i>
        <input type="search" bind:value={playlistFilter} aria-label="Buscar en tus playlists" placeholder={mobile?"Buscar en tus playlists…":"Buscar en tus playlists"}></label>
      {#if mobile}<details class="list-options"><summary aria-label="Opciones de playlists"><i class="ph ph-dots-three-vertical"></i></summary>
        <div><label>Ordenar playlists <select bind:value={playlistSort}><option value="recent">Recientes</option><option value="name">Nombre</option><option value="size">Numero de canciones</option></select></label>
        <button on:click={e=>{e.currentTarget.closest('details').open=false;openCreateMixed();}}>Nueva lista con canciones externas</button></div>
      </details>{/if}
    </div>
    {#if !mobile}    <label class="sort"><i aria-hidden="true" class="ph ph-arrows-down-up"></i><span class="sr-only">Ordenar playlists</span>
      <select bind:value={playlistSort} aria-label="Ordenar playlists">
        <option value="recent">Recientes</option><option value="name">Nombre</option><option value="size">Numero de canciones</option>
      </select></label>
{/if}
    <ul class="lists">
      {#if !playlistFilter}
        <li><button class="list" on:click={()=>dispatch('favorites')}>
          <span class="art"><Cover variant="liked" /></span>
          <span class="text"><b>Tus favoritos</b>{#if !mobile}<small>Lista · canciones que te gustan</small>{/if}</span>
          {#if !mobile}<i aria-hidden="true" class="ph ph-caret-right chevron"></i>{/if}</button></li>
      {/if}
      {#each sortedPlaylists as p (p.kind+p.id)}
        <li><button class="list" aria-label={`Abrir ${p.name}`} on:click={() => push({ type: p.kind==='mixed'?'mixed':'playlist', id: p.id, label: p.name })}>
            {#if p.kind==='mixed'&&!p.coverArt}<span class="art mixed"><i aria-hidden="true" class="ph ph-playlist"></i></span>
            {:else}<span class="art"><Cover covers={p.coverArt?[coverArtUrl(p.coverArt,96)]:(p.covers||[])} size={96} /></span>{/if}
            <span class="text"><b>{p.name}</b><small>{p.kind==='mixed'?'con canciones externas · ':mobile?'':'Playlist · '}{p.songCount || 0} {p.songCount === 1 ? 'cancion' : 'canciones'}</small></span></button>
          <button class="more" aria-label={`Opciones de ${p.name}`} on:click={e => openDots(e, p)}><i aria-hidden="true" class="ph ph-dots-three-vertical"></i></button></li>
      {/each}
      {#if !mobile && !playlistFilter}
        <li><button class="list" on:click={openCreateMixed}>
          <span class="art mixed"><i aria-hidden="true" class="ph ph-plus"></i></span>
          <span class="text"><b>Nueva lista con canciones externas</b><small>Mezcla tu biblioteca con canciones de YouTube sin descargarlas</small></span></button></li>
      {/if}
    </ul>
    {#if !sortedPlaylists.length}
      <p class="none">{playlistFilter?`Ninguna playlist coincide con «${playlistFilter}».`:'Todavia no tienes playlists. Crea una o importa una lista.'}</p>
    {/if}
  {:else if top.type === 'mixed'}
    {#key top.id}<MixedPlaylists initialId={top.id||null} />{/key}
  {:else if top.type === 'playlist'}
    {#if mobile}
      <PhonePlaylist title={top.label} {songs} playlistId={top.id} cover={detailCover} onRefresh={()=>loadPlaylist(top.id)} on:back={()=>goTo(0)}>
        <div slot="organize"><details><summary>Reordenar canciones</summary>{#each songs as song,i}<div class="flex items-center gap-3 p-2"><span class="flex-1 truncate">{i+1}. {song.title}</span><button aria-label={`Subir ${song.title}`} disabled={i===0} on:click={()=>moveSong(i,-1)}>↑</button><button aria-label={`Bajar ${song.title}`} disabled={i===songs.length-1} on:click={()=>moveSong(i,1)}>↓</button></div>{/each}</details></div>
        <button class="add-song" on:click={()=>openSongPicker(top.id,top.label)}><i class="ph ph-plus"></i>Añadir a esta lista</button>
      </PhonePlaylist>
    {:else}
    {#if detailCover?.startsWith('armonia-art-')}<img src={coverArtUrl(detailCover,256)} alt={`Portada de ${top.label}`} width="96" height="96">{/if}
    <div class="flex justify-end mb-2">
      <button on:click={() => openSongPicker(top.id, top.label)}
        class="flex items-center gap-2 px-4 py-2 bg-white/5 hover:bg-white/10 text-sm font-medium rounded-xl transition-colors">
        <i class="ph ph-plus text-sm"></i> Añadir canciones
      </button>
    </div>
    {#if !songs.length}
      <p class="text-center py-12 text-armonia-muted">Esta playlist no tiene canciones todavia.</p>
    {:else}
      <details class="mb-4"><summary>Reordenar canciones</summary>{#each songs as song,i}<div class="flex items-center gap-3 p-2"><span class="flex-1 truncate">{i+1}. {song.title}</span><button aria-label={`Subir ${song.title}`} disabled={i===0} on:click={()=>moveSong(i,-1)}>↑</button><button aria-label={`Bajar ${song.title}`} disabled={i===songs.length-1} on:click={()=>moveSong(i,1)}>↓</button></div>{/each}</details>
      <TrackList {songs} playlistName={top.label} playlistId={top.id} onRefresh={() => loadPlaylist(top.id)} />
    {/if}
    {/if}
  {/if}
</div>

<!-- Create playlist dialog -->
<dialog bind:this={createDialogEl} on:close={() => { createOpen = false; }}
  class="bg-armonia-surface text-armonia-text border border-white/10 rounded-2xl p-6 min-w-[320px] max-w-[90vw] shadow-2xl backdrop:bg-black/70 backdrop:backdrop-blur-xs">
  <h3 class="text-lg font-semibold mb-4 flex items-center gap-2">
    <i class="ph-fill ph-playlist text-armonia-accent"></i> Nueva playlist
  </h3>
  <input type="text" bind:value={createName} placeholder="Nombre de la playlist" autofocus
    on:keydown={e => { if (e.key === 'Enter') createPlaylist(); }}
    class="w-full bg-armonia-bg text-armonia-text placeholder-armonia-muted rounded-xl py-3 px-4 mb-5 focus:outline-hidden focus:ring-2 focus:ring-armonia-accent/50 border border-white/10">
  <div class="flex gap-3 justify-end">
    <button on:click={() => createDialogEl?.close()} class="px-5 py-2.5 bg-white/5 hover:bg-white/10 rounded-xl text-sm font-medium transition-colors">Cancelar</button>
    <button on:click={createPlaylist} class="px-5 py-2.5 bg-armonia-accent hover:bg-armonia-accentHover text-armonia-bg rounded-xl text-sm font-semibold transition-colors">Crear</button>
  </div>
</dialog>

<!-- Rename dialog -->
<dialog bind:this={renameDialogEl} on:close={() => { renameOpen = false; }}
  class="bg-armonia-surface text-armonia-text border border-white/10 rounded-2xl p-6 min-w-[320px] max-w-[90vw] shadow-2xl backdrop:bg-black/70 backdrop:backdrop-blur-xs">
  <h3 class="text-lg font-semibold mb-4">Cambiar nombre</h3>
  <input type="text" bind:value={renameName}
    on:keydown={e => { if (e.key === 'Enter') renamePlaylist(); }}
    class="w-full bg-armonia-bg text-armonia-text placeholder-armonia-muted rounded-xl py-3 px-4 mb-5 focus:outline-hidden focus:ring-2 focus:ring-armonia-accent/50 border border-white/10">
  <div class="flex gap-3 justify-end">
    <button on:click={() => renameDialogEl?.close()} class="px-5 py-2.5 bg-white/5 hover:bg-white/10 rounded-xl text-sm font-medium transition-colors">Cancelar</button>
    <button on:click={renamePlaylist} class="px-5 py-2.5 bg-armonia-accent hover:bg-armonia-accentHover text-armonia-bg rounded-xl text-sm font-semibold transition-colors">Guardar</button>
  </div>
</dialog>

{#if phoneAdder}<PhoneAddSongs id={phoneAdder.id} name={phoneAdder.name} on:close={phoneAdderClosed} />{/if}

<!-- Song picker dialog -->
<dialog bind:this={spDialogEl} on:close={() => { songPickerOpen = false; }}
  class="bg-armonia-surface text-armonia-text border border-white/10 rounded-2xl p-0 w-[90vw] max-w-lg shadow-2xl backdrop:bg-black/70 backdrop:backdrop-blur-xs overflow-hidden">
  <div class="p-4"><h3>Añadir canciones a {songPickerPlaylistName}</h3>{#key songPickerPlaylistId}<PlaylistSearch localOnly={true} onAdd={addLocal} />{/key}<button class="p-3" on:click={()=>spDialogEl?.close()}>Cerrar</button></div>
</dialog>

<!-- Import playlist: a full screen on a phone, as in the app; a window on wider screens -->
{#if !mobile}<dialog bind:this={importDialogEl} on:close={() => { importOpen = false; stopPreview(); }} class="import-dialog" aria-labelledby="import-title">
  <header class="import-bar">
    <button class="import-back" aria-label="Volver; la importacion sigue en segundo plano" title="Volver" on:click={hideImport}><i aria-hidden="true" class="ph ph-arrow-left"></i></button>
    <h2 id="import-title">Importar playlist</h2>
  </header>
  <div class="import-body">
    <ImportReview visible={importOpen} onRefresh={loadPlaylists} onOpenPending={()=>{hideImport();showView('manual-inbox');}}
      onImportAll={()=>{hideImport();showView('import-all');}} />
  </div>
</dialog>{/if}

<!-- New mixed list (web only: lists with external songs are made here) -->
<dialog bind:this={mixedDialogEl}
  class="bg-armonia-surface text-armonia-text border border-white/10 rounded-2xl p-6 min-w-[320px] max-w-[90vw] shadow-2xl backdrop:bg-black/70 backdrop:backdrop-blur-xs">
  <form on:submit|preventDefault={createMixed}>
    <h3 class="text-lg font-semibold mb-4">Nueva lista con canciones externas</h3>
    <input type="text" bind:value={mixedName} required maxlength="150" placeholder="Nombre de la lista" aria-label="Nombre de la lista"
      class="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm mb-4 focus:outline-hidden focus:border-armonia-accent/50">
    {#if mixedError}<p class="text-red-400 text-sm mb-3" role="alert">{mixedError}</p>{/if}
    <div class="flex gap-3 justify-end">
      <button type="button" on:click={()=>mixedDialogEl?.close()} class="px-5 py-2.5 bg-white/5 hover:bg-white/10 rounded-xl text-sm font-medium">Cancelar</button>
      <button disabled={!mixedName.trim()} class="px-5 py-2.5 bg-armonia-accent text-armonia-bg rounded-xl text-sm font-semibold disabled:opacity-50">Crear</button>
    </div>
  </form>
</dialog>

<!-- Re-entry pill: shows while an import is tracked but the dialog is closed -->
{#if $activeImport && importWorkState($activeImport).pending && !importOpen}
  <button on:click={reopenImport}
    class="fixed bottom-24 right-6 z-40 flex items-center gap-2 px-4 py-3 rounded-full bg-armonia-surface border border-white/10 shadow-2xl hover:bg-white/10 transition-colors">
    {#if $activeImport.status === 'running'}
      <i aria-hidden="true" class="ph ph-circle-notch text-armonia-accent animate-spin-slow"></i>
      <span class="text-sm font-medium">Importando {$activeImport.current}/{$activeImport.total}</span>
    {:else}
      <i aria-hidden="true" class="ph ph-clock-countdown text-armonia-accent"></i>
      <span class="text-sm font-medium">{importWorkState($activeImport).label}</span>
    {/if}
  </button>
{/if}

<style>
  .toolbar{display:flex;gap:8px;align-items:center;margin-bottom:10px}
  .filter{flex:1;min-width:0;display:flex;align-items:center;gap:8px;background:#ffffff14;border-radius:8px;padding:0 12px;height:42px;color:var(--color-armonia-muted)}
  .filter input{flex:1;min-width:0;background:transparent;border:0;outline:0;color:var(--color-armonia-text);font-size:.95rem}
  .filter:focus-within{outline:2px solid var(--color-armonia-accent)}
  .sort{display:inline-flex;align-items:center;gap:6px;color:var(--color-armonia-text);font-size:.9rem;font-weight:600;margin:4px 0 6px}
  .sort select{background:transparent;border:0;color:inherit;font:inherit;padding:6px 2px}
  .sort option{background:#1f1c26}
  .sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
  .lists{list-style:none;margin:0;padding:0}
  .lists li{display:flex;align-items:center}
  .list{flex:1;min-width:0;display:flex;align-items:center;gap:14px;padding:7px 6px;border-radius:8px;text-align:left}
  .list:hover,.list:focus-visible{background:#ffffff0d}
  .art{width:60px;height:60px;flex-shrink:0;display:block}
  .art.mixed{display:grid;place-items:center;border-radius:8px;background:#ffffff14;color:var(--color-armonia-muted);font-size:1.7rem}
  .text{flex:1;min-width:0;display:flex;flex-direction:column}
  .text b{font-weight:500;font-size:1.02rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .text small{color:var(--color-armonia-muted);font-size:.85rem}
  .chevron{color:var(--color-armonia-muted)}
  .more{width:44px;height:44px;display:grid;place-items:center;border-radius:50%;color:var(--color-armonia-muted);font-size:1.3rem;flex-shrink:0}
  .more:hover{color:#fff;background:#ffffff14}
  .none{color:var(--color-armonia-muted);padding:32px 8px;text-align:center}
  .import-dialog{margin:0;padding:0;border:0;width:100vw;max-width:100vw;height:100dvh;max-height:100dvh;background:var(--color-armonia-bg,#121015);color:var(--color-armonia-text);display:none;flex-direction:column}
  .import-dialog[open]{display:flex}
  .import-dialog::backdrop{background:#000b}
  @media(min-width:768px){.import-dialog{margin:auto;width:min(640px,92vw);height:auto;max-height:88vh;border-radius:20px;background:#1a1720;border:1px solid #ffffff1a;box-shadow:0 20px 60px #000a}}
  .import-bar{display:flex;align-items:center;gap:6px;padding:calc(8px + env(safe-area-inset-top,0px)) 8px 4px;flex:none}
  .import-bar h2{font-size:1.5rem;font-weight:700;color:#fff}
  .import-back{width:44px;height:44px;display:grid;place-items:center;border-radius:50%;font-size:1.4rem}
  .import-back:hover{background:#ffffff14}
  .import-body{flex:1;min-height:0;overflow-y:auto;padding:4px 16px calc(24px + env(safe-area-inset-bottom,0px))}
</style>
