<script>
  import {playList} from '../lib/stores/playerStore.js';
  import ShuffleToggle from './ShuffleToggle.svelte';
  export let filterQuery='',sortKey='added-desc',songs=[],placeholder,search=true;
</script>
{#if search}
  <label class="phone-song-filter"><i class="ph ph-magnifying-glass"></i><input type="search" bind:value={filterQuery} aria-label={placeholder} {placeholder}></label>
{/if}
<div class="song-actions">
  <label>Orden: <select bind:value={sortKey} aria-label="Ordenar canciones">
    {#each [['added-desc','Añadidas recientemente'],['artist-asc','Artista A → Z'],['artist-desc','Artista Z → A'],['title-asc','A → Z'],['title-desc','Z → A'],['duration-asc','Mas cortas'],['duration-desc','Mas largas']] as [id,label]}<option value={id}>{label}</option>{/each}
  </select></label>
  <ShuffleToggle/><button class="phone-play" disabled={!songs.length} on:click={()=>playList(songs)}><i class="ph-fill ph-play"></i> Reproducir</button>
</div>
