<script>
  import ShuffleToggle from '../components/ShuffleToggle.svelte';
  import {externalMenu} from '../lib/trackActions.js';
  import {library as libApi,streamUrl} from '../lib/api.js';
  import {showContextMenu} from '../lib/stores/contextMenuStore.js';
  import {showPlaylistPicker} from '../lib/stores/playlistPickerStore.js';
  import {playNext} from '../lib/stores/playerStore.js';
  import PlaylistSearch from '../components/PlaylistSearch.svelte';
  import {uniqueAdditions} from '../lib/playlistEdits.js';
  import {showToast} from '../lib/stores/toastStore.js';
  import {onMount} from 'svelte';
  import {api,toQueueTrack,fromQueueTrack} from '../lib/homelab.js';
  import {playList,playQueue,currentTrack} from '../lib/stores/playerStore.js';
  export let initialId=null;
  let playlists=[], selected=null, name='', error='', busy=false,filter='',sort='original',toolsOpen=false,touchStart=0;
  $: rows=(selected?.items||[]).map((item,i)=>({item,i})).filter(({item})=>`${item.track.title} ${item.track.artist}`.toLowerCase().includes(filter.toLowerCase())).sort((a,b)=>sort==='original'?a.i-b.i:a.item.track[sort].localeCompare(b.item.track[sort]));
  async function load(){playlists=(await api.playlists()).playlists;}
  async function act(fn){busy=true;error='';try{await fn();}catch(e){error=e.message;}finally{busy=false;}}
  onMount(()=>act(async()=>{await load();if(initialId)selected=await api.playlist(initialId);}));
  async function save(next){selected=await api.save(next);await load();}
  function move(i,d){const items=[...selected.items];[items[i],items[i+d]]=[items[i+d],items[i]];void act(()=>save({...selected,items}));}
  async function addTracks(tracks){const result=uniqueAdditions(selected.items.map(i=>i.track),tracks,t=>`${t.source}:${t.source_id}`);if(result.added.length)await save({...selected,items:[...selected.items,...result.added.map(track=>({id:crypto.randomUUID(),track}))]});showToast(`${result.added.length} añadidas · ${result.duplicates} ya estaban`);}
  function menu(e,t,i){
    const extra=[...(i>0?[{label:'Subir en la playlist',action:()=>move(i,-1)}]:[]),...(i<selected.items.length-1?[{label:'Bajar en la playlist',action:()=>move(i,1)}]:[]),{label:'Quitar de esta playlist',action:()=>act(()=>save({...selected,items:selected.items.filter((_,n)=>n!==i)}))}];
    if(t.source!=='navidrome')return externalMenu(e.currentTarget,t,extra);
    showContextMenu(e.currentTarget,[{label:'Añadir a favoritos',icon:'ph ph-heart',action:()=>libApi('star',{id:t.source_id}).catch(e=>showToast(e.message,'error'))},
    {label:'Reproducir a continuación',icon:'ph ph-queue',action:()=>playNext(toQueueTrack(t))},
    {label:'Añadir a playlist',icon:'ph ph-playlist',action:()=>showPlaylistPicker([t])},
    ...[0,1,2,3,4,5].map(rating=>({label:rating?`Valorar ${rating} estrellas`:'Quitar valoración',action:()=>libApi('setRating',{id:t.source_id,rating}).then(()=>showToast('Valoración guardada')).catch(e=>showToast(e.message,'error'))})),
    {label:'Descargar archivo',action:()=>{const a=document.createElement('a');a.href=streamUrl(t.source_id);a.download=t.title;a.click();}},...extra]);
  }
  function addCurrent(){return addTracks([fromQueueTrack($currentTrack)]);}
</script>
<section class="music-page">
  {#if !initialId}<h2>Playlists</h2>{/if}
  {#if error}<p role="alert" class="error">{error}</p><button disabled={busy} on:click={()=>act(async()=>{await load();selected=playlists.some(p=>p.id===selected?.id)?await api.playlist(selected.id):null;})}>Recargar sin sobrescribir</button>{/if}
  {#if !initialId}<form class="actions" on:submit|preventDefault={()=>act(async()=>{await save({name,revision:0,items:[]});name='';})}>
    <label>Nueva playlist<input bind:value={name} required maxlength="150"></label><button disabled={busy}>Crear playlist</button>
  </form>
  <div class="actions">{#each playlists as p}<button disabled={busy} on:click={()=>act(async()=>selected=await api.playlist(p.id))} aria-pressed={selected?.id===p.id}>{p.name} ({p.item_count??p.items?.length??0})</button>{/each}</div>
  {/if}
  {#if selected}
    <div class="music-card">
      <div role="group" aria-label="Controles de playlist" on:touchstart={e=>touchStart=e.touches[0].clientY} on:touchend={e=>{if(e.changedTouches[0].clientY-touchStart>55)toolsOpen=true;}}>
        {#if toolsOpen}<input aria-label="Buscar en la playlist" bind:value={filter} placeholder="Buscar en la playlist"><label>Ordenar<select bind:value={sort}><option value="original">Orden original</option><option value="title">Título</option><option value="artist">Artista</option></select></label>{/if}
        <h2>{selected.name}</h2><p>{selected.items.length} canciones</p><button aria-expanded={toolsOpen} on:click={()=>toolsOpen=!toolsOpen}>Buscar y ordenar</button>
      </div>
      <details><summary>Editar playlist y añadir canciones</summary>
      <label>Nombre<input disabled={busy} bind:value={selected.name} maxlength="150"></label>
      <div class="actions">
        <button disabled={busy} on:click={()=>act(()=>save(selected))}>Guardar nombre</button>
        <button disabled={busy||!$currentTrack} on:click={()=>act(addCurrent)}>Añadir canción del reproductor</button>
        <button disabled={busy} on:click={()=>act(async()=>{const r=await api.export(selected);error=`Copia creada en Navidrome: ${r.exported} canciones; ${r.omitted} externas omitidas.`;})}>Exportar copia local</button>
        <button disabled={busy} on:click={()=>{if(confirm(`¿Eliminar “${selected.name}”? Los archivos musicales se conservan.`))void act(async()=>{await api.remove(selected);selected=null;await load();});}}>Eliminar playlist</button>
      </div>
      {#key selected.id}<PlaylistSearch onAdd={addTracks} />{/key}
      </details>
      <div class="actions">        <button disabled={!selected.items.length} on:click={()=>playList(selected.items.map(i=>({...toQueueTrack(i.track),_playlist:{kind:'mixed',id:selected.id}})))}>Reproducir</button>
        <ShuffleToggle />
</div>
      {#each rows as {item,i} (item.id)}
        <div class="music-row"><button on:click={()=>playQueue(selected.items.map(x=>({...toQueueTrack(x.track),_playlist:{kind:'mixed',id:selected.id}})),i)}>{i+1}. {item.track.title}<small>{item.track.artist}</small></button>
          <div class="actions">
            <button aria-label={`Opciones de ${item.track.title}`} on:click={e=>menu(e,item.track,i)}>⋮</button>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</section>
