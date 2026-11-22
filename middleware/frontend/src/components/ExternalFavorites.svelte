<script>
  import {onMount} from 'svelte';
  import {call} from '../lib/api.js';
  import {playQueue} from '../lib/stores/playerStore.js';
  import {toQueueTrack} from '../lib/homelab.js';
  import {externalMenu} from '../lib/trackActions.js';
  let items=[],error='';
  async function load(){try{items=(await call('/api/track-preferences')).items.filter(p=>p.favorite);error='';}catch(e){error=e.message;}}
  onMount(()=>{load();window.addEventListener('music-preferences',load);return()=>window.removeEventListener('music-preferences',load);});
</script>
<section class="music-page"><h2>Favoritos de fuentes externas</h2>
{#if error}<p role="alert">{error}</p>{/if}
{#each items as p,i}<div class="music-row"><button on:click={()=>playQueue(items.map(p=>toQueueTrack(p.track)),i)}>{p.track.title}<small>{p.track.artist} {p.rating?'· '+'★'.repeat(p.rating):''}</small></button><button aria-label={`Opciones de ${p.track.title}`} on:click={e=>externalMenu(e.currentTarget,p.track)}>⋮</button></div>{/each}
{#if !items.length}<p class="muted">Marca una canción desde Buscar o una playlist para guardarla aquí.</p>{/if}</section>
