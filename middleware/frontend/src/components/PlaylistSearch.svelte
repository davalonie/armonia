<script>
  import PreviewControls from './PreviewControls.svelte';
  import {library,search} from '../lib/api.js';
  import {fromQueueTrack,toQueueTrack} from '../lib/homelab.js';
  import {audition} from '../lib/stores/playerStore.js';
  export let localOnly=false;
  export let onAdd=async()=>{};
  let query='',source='local',results=[],selected=new Map(),error='',busy=false,notice='';
  async function find(){
    if(busy||!query.trim())return;busy=true;error='';notice='';
    try{
      if(source==='local'||localOnly)results=((await library('search3',{query,songCount:50,albumCount:0,artistCount:0})).searchResult3?.song||[]).map(fromQueueTrack);
      else results=((await search(query,15)).songs||[]).map(r=>({source:'youtube',source_id:r.videoId,title:r.title,artist:r.channel||'Unknown',album:r.album||'',duration:r.duration||null}));
    }catch(e){error=e.message;}finally{busy=false;}
  }
  const key=t=>`${t.source}:${t.source_id}`;
  function toggle(t){const next=new Map(selected);next.has(key(t))?next.delete(key(t)):next.set(key(t),t);selected=next;}
  async function add(){busy=true;error='';try{const count=selected.size;await onAdd([...selected.values()]);selected=new Map();notice=`Seleccion procesada (${count} canciones).`;}catch(e){error=e.message;}finally{busy=false;}}
  function preview(t){audition(toQueueTrack(t));}
</script>
<section class="music-card">
  <form class="actions" on:submit|preventDefault={find}>
    <label>Buscar canciones<input aria-label="Buscar canciones para playlist" bind:value={query} required maxlength="300"></label>
    {#if !localOnly}<label>Fuente<select bind:value={source}><option value="local">Biblioteca</option><option value="youtube">YouTube Music</option></select></label>{/if}
    <button disabled={busy}>Buscar</button>
  </form>
  {#if localOnly}<p class="muted">Esta playlist contiene archivos de biblioteca. Para añadir fuentes externas sin descargar, crea una lista mixta.</p>{/if}
  {#if busy}<p role="status">Procesando…</p>{/if}
  {#if error}<p role="alert">{error}</p>{/if}
  {#if notice}<p role="status">{notice}</p>{/if}
  <div class="results">
    {#each results as t}<div class="music-row"><label><input type="checkbox" checked={selected.has(key(t))} on:change={()=>toggle(t)}> {t.title} · {t.artist}</label><button on:click={()=>preview(t)}>Preescuchar</button></div>{/each}
  </div>
  <button disabled={busy||!selected.size} on:click={add}>Añadir seleccion ({selected.size})</button>
  <PreviewControls />
</section>
<style>.results{max-height:40vh;overflow:auto}input:not([type=checkbox]),select{max-width:100%;background:#181820;padding:.5rem;border:1px solid #555;border-radius:.4rem}input[type=checkbox]{width:auto}button{padding:.5rem;border:1px solid #555;border-radius:.4rem}button:disabled{opacity:.5}</style>
