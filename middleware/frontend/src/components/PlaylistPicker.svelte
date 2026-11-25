<script>
  import {playlistPickerState,closePlaylistPicker} from '../lib/stores/playlistPickerStore.js';
  import {library,getSession,coverArtUrl,artSize} from '../lib/api.js';
  import {api,fromQueueTrack} from '../lib/homelab.js';
  import {appendLocal,uniqueAdditions} from '../lib/playlistEdits.js';
  import {showToast} from '../lib/stores/toastStore.js';
  let dialogEl,playlists=[],tracks=[],loading=false,busy=false,error='',name='',kind='mixed',filter='',sort='name',generation=0,selected=new Set(),membership={};
  const key=p=>`${p.kind}:${p.id}`;
  $: if($playlistPickerState.open && dialogEl && !dialogEl.open){dialogEl.showModal();void load();}
  $: external=tracks.some(t=>t.source!=='navidrome');
  $: visible=playlists.filter(p=>p.name.toLowerCase().includes(filter.toLowerCase())).sort((a,b)=>sort==='name'?a.name.localeCompare(b.name):(b.songCount??b.item_count??0)-(a.songCount??a.item_count??0));
  async function load(){
    const epoch=++generation,incoming=$playlistPickerState.tracks;
    loading=true;error='';name='';filter='';selected=new Set();membership={};
    try{
      const loaded=await Promise.all(incoming.map(async t=>typeof t==='string'?fromQueueTrack((await library('getSong',{id:t})).song):t.source_id?t:fromQueueTrack(t)));
      const [local,mixed]=await Promise.all([library('getPlaylists'),api.playlists()]);
      if(epoch!==generation)return;
      tracks=loaded;
      playlists=[...(local.playlists?.playlist||[]).filter(p=>p.owner===getSession()?.username).map(p=>({...p,kind:'local'})),...mixed.playlists.map(p=>({...p,kind:'mixed'}))];
      const pending=[...playlists];
      // Three read workers; cancellation never writes anything.
      void Promise.all(Array.from({length:3},async()=>{while(pending.length && epoch===generation){
        const p=pending.shift();if(external&&p.kind==='local')continue;
        try{
          const entries=p.kind==='local'?(await library('getPlaylist',{id:p.id})).playlist?.entry||[]:(await api.playlist(p.id)).items.map(i=>i.track);
          if(epoch!==generation)return;
          const ids=new Set(entries.map(t=>t.source_id?`${t.source}:${t.source_id}`:`navidrome:${t.id}`));
          membership={...membership,[key(p)]:tracks.every(t=>ids.has(`${t.source}:${t.source_id}`))?'included':'available'};
        }catch{if(epoch===generation)membership={...membership,[key(p)]:'unknown'};}
      }}));
    }catch(e){if(epoch===generation)error=e.message;}finally{if(epoch===generation)loading=false;}
  }
  function toggle(p){const next=new Set(selected);next.has(key(p))?next.delete(key(p)):next.add(key(p));selected=next;}
  async function confirm(){
    if(busy)return;busy=true;error='';const failures=[];let added=0;
    try{
      for(const p of playlists.filter(p=>selected.has(key(p)))){
        try{
          if(p.kind==='local'){const result=await appendLocal(p.id,tracks.map(t=>t.source_id));added+=result.added;}
          else{const current=await api.playlist(p.id);const change=uniqueAdditions(current.items.map(i=>i.track),tracks,t=>`${t.source}:${t.source_id}`);
            if(change.added.length)await api.save({...current,items:[...current.items,...change.added.map(track=>({id:crypto.randomUUID(),track}))]});added+=change.added.length;}
          selected=new Set([...selected].filter(k=>k!==key(p)));membership={...membership,[key(p)]:'included'};
        }catch(e){failures.push(`${p.name}: ${e.message}`);}
      }
      if(added)showToast(`${added} canciones añadidas`);
      $playlistPickerState.onDone?.();
      if(failures.length)error=failures.join(' · ');else dialogEl.close();
    }finally{busy=false;}
  }
  async function create(){
    if(busy||!name.trim())return;busy=true;error='';
    try{
      let p;
      if(kind==='local'&&!external)p={...(await library('createPlaylist',{name:name.trim()})).playlist,kind:'local'};
      else p={...await api.save({name:name.trim(),revision:0,items:[]}),kind:'mixed'};
      playlists=[...playlists,p];selected=new Set([...selected,key(p)]);name='';
      showToast('Playlist creada. Pulsa Hecho para añadir las canciones.');
    }catch(e){error=e.message;}finally{busy=false;}
  }
</script>
<dialog bind:this={dialogEl} on:cancel={e=>{if(busy)e.preventDefault();}} on:close={()=>{generation++;closePlaylistPicker();}} aria-labelledby="picker-title" class="bg-armonia-surface text-armonia-text border border-white/10 rounded-2xl p-5 w-[92vw] max-w-lg backdrop:bg-black/70">
  <header class="flex items-center justify-between gap-3"><button disabled={busy} on:click={()=>dialogEl.close()}>Cancelar</button><h3 id="picker-title" class="text-lg font-semibold">Añadir a playlist</h3><button disabled={busy||!selected.size} on:click={confirm}>Hecho</button></header>
  {#if error}<p role="alert" class="text-red-300 my-3">{error}</p>{/if}
  {#if loading}<p role="status">Cargando playlists…</p>{:else}
    <p class="text-sm my-3">{tracks.length} canciones · {selected.size} playlists seleccionadas. Las canciones ya incluidas se conservan.</p>
    <input aria-label="Filtrar playlists" bind:value={filter} placeholder="Buscar playlist" class="w-full bg-black/20 p-3 rounded-lg">
    <label>Ordenar <select bind:value={sort}><option value="name">Nombre</option><option value="count">Numero de canciones</option></select></label>
    <div class="max-h-72 overflow-auto my-3">
      {#each visible as p (key(p))}<label class="picker-row">
        {#if p.coverArt}<img src={coverArtUrl(p.coverArt,artSize(48,96))} alt="" loading="lazy">{:else}<span class="cover" aria-hidden="true">♫</span>{/if}
        <span class="name">{p.name}<small>{p.songCount??p.item_count??p.items?.length??0} canciones · {membership[key(p)]==='included'?'Ya incluida':membership[key(p)]==='unknown'?'Se comprobara al guardar':p.kind==='mixed'?'Admite fuentes externas':'Biblioteca'}</small></span>
        <input type="checkbox" checked={selected.has(key(p))||membership[key(p)]==='included'} disabled={busy||membership[key(p)]==='included'||(external&&p.kind==='local')} on:change={()=>toggle(p)} aria-label={`Seleccionar ${p.name}`}>
      </label>{/each}
      {#if !visible.length}<p>No hay playlists con ese nombre.</p>{/if}
    </div>
    <form on:submit|preventDefault={create} class="border-t border-white/10 pt-3">
      <label>Nueva playlist<input bind:value={name} maxlength="150" required class="w-full bg-black/20 p-2 rounded-lg"></label>
      {#if !external}<label>Contenido<select bind:value={kind}><option value="mixed">Biblioteca y fuentes externas</option><option value="local">Solo biblioteca</option></select></label>{/if}
      <button disabled={busy} class="p-3">Crear playlist</button>
    </form>
  {/if}
</dialog>
<style>.picker-row{display:flex;align-items:center;gap:.8rem;padding:.6rem 0}.picker-row img,.cover{width:48px;height:48px;object-fit:cover;border-radius:.4rem}.cover{display:grid;place-items:center;background:#62458b;font-size:1.5rem}.name{flex:1}.name small{display:block;color:#bbb;font-size:.75rem}select{background:#211c29;padding:.6rem}input[type=checkbox]{width:24px;height:24px;accent-color:#c4a3ff}header button{padding:.5rem;color:#d9c2ff}</style>
