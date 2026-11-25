<script>
  import MaterialIcon from './MaterialIcon.svelte';
  // «Añadir canciones» on the phone, as the Kotlin screen was: search the library, tap a cover to
  // listen to ten seconds, + saves that one song at once and the screen stays open to keep adding.
  // Only library songs: a Navidrome playlist cannot hold a song from outside it.
  import {createEventDispatcher,onMount} from 'svelte';
  import Cover from './Cover.svelte';
  import {library,coverArtUrl} from '../lib/api.js';
  import {librarySongs} from '../lib/librarySongs.js';
  import {replaceLocal} from '../lib/playlistEdits.js';
  import {audition,stopPreview,previewState,playbackProgress} from '../lib/stores/playerStore.js';
  import {showToast} from '../lib/stores/toastStore.js';
  import {matchesSearch} from '../lib/textSearch.js';

  export let id;
  export let name='';
  /** How the list is read and changed; a Navidrome playlist by default. A mixed list passes its own. */
  export let list=null;
  const dispatch=createEventDispatcher();
  // A second tap of a double tap must not undo what the first one has just added.
  const UNDO_GUARD_MS=700;
  const PAGE=120;

  let dialog,query='',songs=[],loading=true,error='',inPlaylist=new Set(),states={},addedAt={},shownCount=PAGE;

  const matches=(q,song)=>matchesSearch(q,song.title,song.artist,song.album);
  const byArtistThenTitle=(a,b)=>(a.artist||'').toLowerCase().localeCompare((b.artist||'').toLowerCase())||(a.title||'').toLowerCase().localeCompare((b.title||'').toLowerCase());

  async function navidromeIds(){return ((await library('getPlaylist',{id})).playlist?.entry||[]).map(s=>s.id);}
  const navidrome={
    ids:navidromeIds,
    append:async song=>{const ids=await navidromeIds();if(!ids.includes(song.id))await replaceLocal(id,ids,[...ids,song.id]);},
    removeLast:async songId=>{const ids=await navidromeIds(),at=ids.lastIndexOf(songId);if(at>=0)await replaceLocal(id,ids,ids.filter((_,i)=>i!==at));},
  };
  $: store=list||navidrome;
  const currentIds=()=>store.ids();
  async function load(){
    loading=true;error='';
    try{
      const [all,ids]=await Promise.all([librarySongs(),currentIds()]);
      songs=[...all].sort(byArtistThenTitle);
      inPlaylist=new Set(ids);
    }catch{error='No se pudo cargar tu biblioteca. Comprueba la conexion.';}
    finally{loading=false;}
  }
  // Not modal: a modal dialog sits in the top layer and would hide the «Deshacer» toast.
  onMount(()=>{dialog.show();void load();});

  const stateOf=song=>states[song.id]??(inPlaylist.has(song.id)?'already':'none');
  const setState=(song,value)=>{states={...states,[song.id]:value};};

  // Added only if absent, so a retry after a lost answer never duplicates the song.
  async function add(song){
    const before=stateOf(song);
    if(before==='sending'||before==='added'||before==='already')return;
    setState(song,'sending');
    try{
      await store.append(song);
      addedAt[song.id]=Date.now();
      inPlaylist=new Set([...inPlaylist,song.id]);
      setState(song,'added');
      showToast(`«${song.title}» añadida`,'info',()=>undo(song));
    }catch{
      setState(song,'failed');
      showToast(`No se pudo añadir «${song.title}». Pulsa + para reintentar.`,'error');
    }
  }
  // Only what this screen added can be undone: the last occurrence, if nobody changed the list meanwhile.
  async function undo(song){
    if(states[song.id]!=='added'||Date.now()-(addedAt[song.id]||0)<UNDO_GUARD_MS)return;
    setState(song,'sending');
    try{
      await store.removeLast(song.id);
      const rest={...states};delete rest[song.id];states=rest;
      inPlaylist=new Set([...inPlaylist].filter(x=>x!==song.id));
    }catch{
      setState(song,'added');
      showToast(`No se pudo deshacer. «${song.title}» sigue en la playlist.`,'error');
    }
  }

  // Ten seconds from the middle; tapping the song that is sounding stops it. Never adds anything.
  const preview=song=>audition(song,true);
  function close(){stopPreview();dispatch('close');}
  function more(e){const el=e.currentTarget;if(el.scrollTop+el.clientHeight>el.scrollHeight-600&&shownCount<shown.length)shownCount+=PAGE;}

  $: shown=query.trim()?songs.filter(s=>matches(query.trim(),s)):songs;
  $: query,shownCount=PAGE;
  $: previewing=$previewState?.track?.id;
  $: fraction=$playbackProgress.duration>0?Math.min(1,$playbackProgress.currentTime/$playbackProgress.duration):0;
  const credits=s=>[s.artist,s.album].filter(Boolean).join(' · ');
  const label={already:'Ya esta en la playlist · ',added:'Añadida · ',failed:'No se pudo añadir · '};
</script>

<dialog bind:this={dialog} class="add-songs" aria-labelledby="add-songs-title" on:close={close}>
  <header>
    <button class="icon" data-phone-back aria-label="Volver a la playlist" on:click={()=>dialog.close()}><i class="ph ph-arrow-left"></i></button>
    <div class="title"><h1 id="add-songs-title">Añadir canciones</h1><p>a «{name}»</p></div>
  </header>
  <form class="field" role="search" on:submit|preventDefault>
    <MaterialIcon name="search" />
    <input bind:value={query} type="search" enterkeyhint="search" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="Buscar cancion o artista" aria-label="Buscar cancion o artista">
    {#if query}<button type="button" class="clear" aria-label="Borrar la busqueda" on:click={()=>query=''}><i class="ph ph-x"></i></button>{/if}
  </form>
  <p class="hint">Canciones de tu biblioteca. Toca una portada para escuchar 10 segundos; + la añade.</p>
  {#if loading}
    <p class="status" role="status"><i class="ph ph-circle-notch animate-spin-slow"></i></p>
  {:else if error}
    <div class="status"><p role="alert" class="error">{error}</p><button class="retry" on:click={load}>Reintentar</button></div>
  {:else if !shown.length}
    <p class="status muted">{songs.length?`No hay canciones en tu biblioteca para «${query.trim()}». Las de fuera se añaden desde Buscar, descargandolas antes.`:'Tu biblioteca todavia no tiene canciones.'}</p>
  {:else}
    <ul class="rows" on:scroll={more}>
      {#each shown.slice(0,shownCount) as song (song.id)}
        {@const state=states[song.id]??(inPlaylist.has(song.id)?'already':'none')}
        {@const playingNow=previewing===song.id}
        <li>
          <button class="art" aria-label={playingNow?`Parar la preescucha de ${song.title}`:`Escuchar 10 segundos de ${song.title}`} on:click={()=>preview(song)}>
            <Cover covers={song.coverArt?[coverArtUrl(song.coverArt,128)]:[]} size={128} />
            {#if playingNow}
              <span class="ring"><svg viewBox="0 0 36 36" aria-hidden="true"><circle cx="18" cy="18" r="16" class="track"/><circle cx="18" cy="18" r="16" class="done" stroke-dasharray={`${fraction*100.53} 100.53`}/></svg><i class="ph-fill ph-stop"></i></span>
            {:else}<span class="play"><i class="ph-fill ph-play"></i></span>{/if}
          </button>
          <span class="text"><b>{song.title}</b><small class={state}>{label[state]||''}{credits(song)}</small></span>
          {#if state==='sending'}<span class="icon" role="status" aria-label={`Guardando ${song.title}`}><i class="ph ph-circle-notch animate-spin-slow"></i></span>
          {:else if state==='added'}<button class="icon added" aria-label={`Añadida. Toca para quitar ${song.title} de la playlist`} on:click={()=>undo(song)}><i class="ph-fill ph-check-circle"></i></button>
          {:else if state==='already'}<span class="icon already" aria-label={`${song.title} ya esta en la playlist`}><i class="ph-fill ph-check-circle"></i></span>
          {:else if state==='failed'}<button class="icon failed" aria-label={`Reintentar añadir ${song.title}`} on:click={()=>add(song)}><i class="ph ph-arrow-clockwise"></i></button>
          {:else}<button class="icon add" aria-label={`Añadir ${song.title} a la playlist`} on:click={()=>add(song)}><i class="ph ph-plus-circle"></i></button>{/if}
        </li>
      {/each}
    </ul>
  {/if}
</dialog>

<style>
  .add-songs{position:fixed;inset:0;z-index:250;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px);box-sizing:border-box;width:100%;height:100%;max-width:none;max-height:none;margin:0;border:0;background:var(--color-armonia-bg,#121212);color:inherit;display:flex;flex-direction:column}
  .add-songs:not([open]){display:none}
  /* imePadding, as AddSongsScreen: the list ends where the keyboard starts (--ime from LibraryActivity). */
  :global(.capacitor.ime-open) .add-songs{padding-bottom:var(--ime)}
  .add-songs::backdrop{background:transparent}
  header{display:flex;align-items:center;gap:4px;height:64px;padding:0 4px;flex:none}
  .title{min-width:0}
  h1{font-size:18px;line-height:24px;font-weight:600}
  .title p{font-size:12px;line-height:16px;color:#c4a3ff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .field{display:flex;align-items:center;gap:10px;margin:4px 16px;padding:0 14px;height:52px;border-radius:28px;background:#2a2a2a;flex:none}
  .field input{flex:1;min-width:0;background:transparent;border:0;outline:0;font-size:16px}
  .field input::-webkit-search-cancel-button{display:none}
  .hint{margin:6px 16px;font-size:12px;line-height:16px;color:#999;flex:none}
  .status{padding:24px;text-align:center}
  .muted{color:#999}
  .error{color:#f2b8b5}
  .retry{margin-top:8px;padding:.5rem 1rem;border:1px solid #555;border-radius:2rem}
  .rows{flex:1;overflow-y:auto;padding-bottom:16px}
  li{display:flex;align-items:center;height:72px;padding:0 4px 0 16px}
  .art{position:relative;width:52px;height:52px;border-radius:8px;overflow:hidden;flex:none;background:#333}
  .art :global(img){width:100%;height:100%;object-fit:cover}
  .play,.ring{position:absolute;inset:0;display:grid;place-items:center;color:#fff}
  .play i{font-size:13px;width:22px;height:22px;display:grid;place-items:center;border-radius:50%;background:rgba(0,0,0,.45)}
  .ring{background:rgba(0,0,0,.55)}
  .ring svg{position:absolute;width:36px;height:36px;left:8px;top:8px;transform:rotate(-90deg)}
  .ring circle{fill:none;stroke-width:3}
  .ring .track{stroke:rgba(255,255,255,.25)}
  .ring .done{stroke:#c4a3ff}
  .ring i{font-size:16px}
  .text{flex:1;min-width:0;margin-left:14px;display:flex;flex-direction:column}
  .text b{font-size:14px;line-height:20px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .text small{margin-top:2px;font-size:12px;line-height:16px;color:#999;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .text small.added{color:#c4a3ff}
  .text small.failed{color:#f2b8b5}
  .icon{width:48px;height:48px;display:grid;place-items:center;font-size:28px;flex:none}
  header .icon{font-size:24px}
  .add,.added{color:#c4a3ff}
  .already{color:rgba(255,255,255,.35)}
  .failed{color:#f2b8b5}
  .clear{font-size:20px}
</style>
