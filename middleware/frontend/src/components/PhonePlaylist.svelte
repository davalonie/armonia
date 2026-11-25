<script>
  import {createEventDispatcher,tick} from 'svelte';
  import TrackList from './TrackList.svelte';
  import PhoneDownloads from './PhoneDownloads.svelte';
  import {currentTrack,playing,togglePlayPause,trackArtUrl} from '../lib/stores/playerStore.js';
  import ShuffleToggle from './ShuffleToggle.svelte';
  import PhonePlayButton from './PhonePlayButton.svelte';
  import {coverArtUrl} from '../lib/api.js';
  import MaterialIcon from './MaterialIcon.svelte';
  import Cover from './Cover.svelte';
  import {matchesSearch} from '../lib/textSearch.js';

  export let title, songs=[], playlistId=null, cover=null, offline=false, onRefresh=null;
  // A mixed list (library and external songs) uses this same screen: its own kind, the entries its
  // rows add to the song menu, and its options behind three dots in the head.
  export let kind='local', rowMenu=null, menu=null;
  const dispatch=createEventDispatcher();
  let list,caption='';
  // The app's «Buscar y ordenar»: the magnifier turns into a close button over a rounded field and
  // three order chips; closing it forgets the search and the order.
  let searchOpen=false,query='',sort='original',field;
  async function toggleSearch(){
    searchOpen=!searchOpen;
    if(!searchOpen){query='';sort='original';return;}
    await tick();field?.focus();
  }
  $: found=query.trim()?songs.filter(s=>matchesSearch(query,s.title,s.artist,s.album)).length:songs.length;
  const ORDERS=[['original','Orden de la lista'],['title','Titulo'],['artist','Artista']];
  $: active = !!playlistId && $currentTrack?._playlist?.kind === kind && $currentTrack?._playlist?.id === playlistId;
  // The cover of the list as Inicio shows it: its own cover, or a mosaic of its songs' covers.
  $: heroCovers=cover?[coverArtUrl(cover,400)]:[...new Set(songs.map(s=>trackArtUrl(s,200)).filter(Boolean))].slice(0,4);
  $: minutes=Math.ceil(songs.reduce((total,s)=>total+(Number(s.duration)||0),0)/60);
</script>
<section class="phone-playlist">
  <!-- The head of a list in Inicio: tinted band, the cover in the middle, «Lista», the name and the count. -->
  <header class="hero">
    <div class="bar">
      <button class="hero-btn" data-phone-back aria-label="Volver" on:click={()=>dispatch('back')}><MaterialIcon name="arrow_back" /></button>
      {#if songs.length}<button class="hero-btn" class:closing={searchOpen} aria-label={searchOpen?'Cerrar la busqueda':'Buscar y ordenar en esta playlist'} aria-expanded={searchOpen} on:click={toggleSearch}><MaterialIcon name={searchOpen?'close':'search'} /></button>{/if}
      {#if menu}<button class="hero-btn" aria-label="Opciones de la playlist" on:click={e=>menu(e.currentTarget)}><MaterialIcon name="more_vert" /></button>{/if}
    </div>
    <div class="hero-cover"><Cover covers={heroCovers} variant="plain" label={title} size={400} /></div>
    <p class="eyebrow">Lista</p>
    <h1>{title}</h1>
    <p class="meta">{songs.length} {songs.length===1?'cancion':'canciones'}{minutes?' · '+minutes+' min':''}</p>
  </header>
  <small>{offline?'En el telefono':(kind==='mixed'?'Con canciones externas · ':'En tu biblioteca · ')+(caption||'No descargada en el telefono')}</small>
  <div class="controls">
    {#if !offline && playlistId}<PhoneDownloads id={playlistId} kind={kind==='mixed'?'mixed':'playlist'} {title} tracks={songs} bind:caption />{/if}
    <div class="space"></div><ShuffleToggle />
    <PhonePlayButton disabled={!songs.length} pause={active && $playing} label="Reproducir la playlist" on:click={()=>active?togglePlayPause():list.playFromHeader()} />
  </div>
  {#if searchOpen}
    <div class="search">
      <label class="field"><MaterialIcon name="search" />
        <input bind:this={field} bind:value={query} type="search" enterkeyhint="search" autocomplete="off" spellcheck="false" placeholder="Buscar en esta playlist" aria-label="Buscar en esta playlist">
        {#if query}<button type="button" aria-label="Borrar la busqueda" on:click={()=>{query='';field.focus();}}><MaterialIcon name="close" /></button>{/if}
      </label>
      <div class="chips" role="group" aria-label="Orden de la playlist">
        {#each ORDERS as [key,label]}<button class="chip" class:selected={sort===key} aria-pressed={sort===key} on:click={()=>sort=key}>{label}</button>{/each}
      </div>
      {#if query.trim()}<p class="count">{found} de {songs.length}</p>{/if}
    </div>
  {/if}
  <slot/>
  <TrackList bind:this={list} {songs} {playlistId} playlistKind={kind} {rowMenu} playlistName={title} {onRefresh} tools={false} filter={query} {sort} />
  {#if !songs.length}<p class="empty">Todavia no hay canciones en esta lista.</p>{/if}
</section>
<style>
  .phone-playlist{padding:0 16px 24px}
  .hero{margin:0 -16px 6px;padding:8px 16px 12px;background:linear-gradient(180deg,#3c3550 0%,#201b2a 62%,var(--color-armonia-bg,#121015) 100%)}
  .bar{display:flex;gap:8px;align-items:center;height:48px}
  .bar>:first-child{margin-right:auto}
  .hero-btn{width:40px;height:40px;border-radius:50%;background:#0000004d;display:grid;place-items:center;color:#fff}
  .hero-cover{width:min(52vw,220px);margin:8px auto 16px}
  .eyebrow{font-size:.75rem;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:#ffffffc0;margin-bottom:.25rem}
  h1{font-size:clamp(1.6rem,6vw,3.4rem);font-weight:800;letter-spacing:-.02em;line-height:1.1;overflow-wrap:anywhere}
  .meta{color:#ffffff99;font-size:.82rem;margin-top:.35rem}
  small{display:block;color:#999;font-size:12px;line-height:18px}
  .controls{display:flex;align-items:center;gap:8px;min-height:72px;margin:2px 0 4px -12px}
  .space{flex:1}
  .empty{text-align:center;margin:28px auto}
  .hero .closing{color:#c4a3ff}
  .search{padding:4px 0}
  .field{display:flex;align-items:center;gap:12px;height:56px;padding:0 4px 0 12px;border-radius:28px;background:#242424;color:#eee}
  .field input{flex:1;min-width:0;height:100%;background:transparent;border:0;outline:0;font-size:16px;line-height:24px;letter-spacing:.5px;color:#eee}
  .field input::placeholder{color:#eeeeee99}
  .field input::-webkit-search-cancel-button{display:none}
  .field button{width:48px;height:48px;display:grid;place-items:center;border-radius:50%}
  .chips{display:flex;gap:8px;padding-top:6px}
  .chip{height:32px;padding:0 12px;border-radius:8px;border:1px solid #222;font-size:14px;line-height:20px;font-weight:500;letter-spacing:.1px;color:#eee}
  .chip.selected{background:#1e1e1e;border-color:#1e1e1e}
  .count{padding-top:6px;font-size:12px;line-height:16px;letter-spacing:.4px;color:#eeeeeea6}
</style>
