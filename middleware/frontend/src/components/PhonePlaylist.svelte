<script>
  import {createEventDispatcher} from 'svelte';
  import TrackList from './TrackList.svelte';
  import PhoneDownloads from './PhoneDownloads.svelte';
  import {currentTrack,playing,togglePlayPause} from '../lib/stores/playerStore.js';
  import ShuffleToggle from './ShuffleToggle.svelte';
  import {coverArtUrl} from '../lib/api.js';

  export let title, songs=[], playlistId=null, cover=null, offline=false, onRefresh=null;
  const dispatch=createEventDispatcher();
  let options=false,list,caption='';
  $: active = !!playlistId && $currentTrack?._playlist?.kind === 'local' && $currentTrack?._playlist?.id === playlistId;
  $: minutes=Math.ceil(songs.reduce((total,s)=>total+(Number(s.duration)||0),0)/60);
</script>
<section class="phone-playlist">
  <header>
    <button class="phone-back" data-phone-back aria-label="Volver" on:click={()=>dispatch('back')}><i class="ph ph-arrow-left"></i></button>
    <button class="phone-back" aria-label="Buscar y ordenar en esta playlist" aria-expanded={options} on:click={()=>options=!options}><i class="ph ph-magnifying-glass"></i></button>
  </header>
  {#if cover?.startsWith('armonia-art-')}<img class="custom-cover" src={coverArtUrl(cover,256)} alt="">{/if}
  <h1>{title}</h1>
  <p>{songs.length} {songs.length===1?'cancion':'canciones'}{minutes?' · '+minutes+' min':''}</p>
  <small>{offline?'En el telefono':'En tu biblioteca · '+(caption||'No descargada en el telefono')}</small>
  <div class="controls">
    {#if !offline && playlistId}<PhoneDownloads id={playlistId} {title} tracks={songs} bind:caption />{/if}
    <div class="space"></div><ShuffleToggle />
    <button class="playlist-play" disabled={!songs.length} on:click={()=>active?togglePlayPause():list.playFromHeader()}>{active && $playing?'Ⅱ Pausar':'▶ Reproducir'}</button>
  </div>
  {#if options}<slot name="organize"/>{/if}
  <slot/>
  <TrackList bind:this={list} {songs} {playlistId} playlistName={title} {onRefresh} tools={false} toolsOpen={options} />
  {#if !songs.length}<p class="empty">Todavia no hay canciones en esta lista.</p>{/if}
</section>
<style>
  .phone-playlist{padding:0 16px 24px}
  header{display:flex;justify-content:space-between;align-items:center;height:64px;margin:0 -12px 4px}
  h1{font-size:24px;line-height:32px;font-weight:700}
  p{font-size:14px;line-height:20px;color:#b3b3b3}
  small{display:block;color:#999;font-size:12px;line-height:18px}
  .controls{display:flex;align-items:center;gap:6px;min-height:72px;margin:2px 0 4px -12px}
  .space{flex:1}
  .playlist-play{padding:.65rem 1rem;border:1px solid #c4a3ff;border-radius:2rem;min-height:44px;background:#c4a3ff;color:#18101f;font-weight:650}
  .playlist-play:disabled{opacity:.45}
  .empty{text-align:center;margin:28px auto}
  .custom-cover{width:96px;height:96px;border-radius:8px;margin-bottom:12px}
</style>
