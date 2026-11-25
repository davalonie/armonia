<script>
  import {pullRefresh} from '../lib/pullRefresh.js';
  import {onMount,createEventDispatcher} from 'svelte';
  import {library,coverArtUrl} from '../lib/api.js';
  import TrackList from './TrackList.svelte';
  import ShuffleToggle from './ShuffleToggle.svelte';
  import PhonePlayButton from './PhonePlayButton.svelte';
  import PhoneDownloads from './PhoneDownloads.svelte';

  export let id,title;
  let album=null,list,error='';
  const dispatch=createEventDispatcher();
  async function load(){
    try{album=(await library('getAlbum',{id})).album;error='';}
    catch(e){error=e.message;}
  }
  onMount(()=>{void load();});
  $: songs=album?.song||[];
  $: art=songs[0]?.coverArt;
</script>

<section use:pullRefresh={load} class="phone-album phone-tracks">
  <header class="phone-toolbar"><button class="phone-back" data-phone-back aria-label="Volver" on:click={()=>dispatch('back')}><i class="ph ph-arrow-left"></i></button><h1>{album?.name||title}</h1></header>
  {#if error}<p role="alert">{error} <button on:click={load}>Reintentar</button></p>
  {:else if !album}<p role="status">Cargando album…</p>
  {:else}
    <div class="album-info">
      <div class="sleeve">{#if art}<img src={coverArtUrl(art,500)} alt="" on:error={e=>e.currentTarget.hidden=true}>{/if}</div>
      <h2>{album.name}</h2><p>{album.artist}</p>
      <small>{songs.length} {songs.length===1?'cancion':'canciones'} · {Math.round((album.duration||songs.reduce((n,s)=>n+(s.duration||0),0))/60)} min</small>
    </div>
    <div class="album-actions">
      <PhoneDownloads {id} title={album.name} tracks={songs} kind="album"/>
      <ShuffleToggle/><PhonePlayButton disabled={!songs.length} label="Reproducir el album" on:click={()=>list.playFromHeader()} />
    </div>
    <TrackList bind:this={list} {songs} tools={false} onRefresh={load}/>
  {/if}
</section>
