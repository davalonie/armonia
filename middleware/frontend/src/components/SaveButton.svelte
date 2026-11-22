<script>
  // The players' + / ✓, as in the app: + when the song is in none of your lists, ✓ when it is in favourites or a
  // playlist. Either way it opens «Guardar en una playlist».
  import {saved, saveSheet, saveTarget, checkSaved} from '../lib/saveSong.js';
  export let track = null;
  export let size = 'md';
  $: target = saveTarget(track);
  $: if (target) checkSaved(track);
  $: key = target ? (target.kind === 'library' ? target.id : `preview|${target.videoId}`) : '';
  $: isSaved = !!$saved[key];
</script>

{#if target}
  <button class="save {size}" class:on={isSaved} aria-label={isSaved ? 'Guardada · cambiar dónde' : 'Guardar en una playlist'}
    title={isSaved ? 'Guardada en tus listas' : 'Guardar en una playlist'} on:click|stopPropagation={() => saveSheet.set(track)}>
    <i aria-hidden="true" class={isSaved ? 'ph-fill ph-check-circle' : 'ph ph-plus-circle'}></i>
  </button>
{/if}

<style>
  .save{flex:none;width:40px;height:40px;display:grid;place-items:center;border-radius:50%;font-size:1.6rem;color:var(--color-armonia-muted)}
  .save.lg{width:44px;height:44px;font-size:2rem}
  .save:hover{background:#ffffff14;color:#fff}
  .save.on,.save.on:hover{color:var(--color-armonia-accent)}
</style>
