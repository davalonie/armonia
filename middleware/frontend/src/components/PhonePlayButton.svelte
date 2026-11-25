<script>
  // The round Play of the app's lists (PlayAndShuffle): 56 dp, accent filled, the symbol only.
  import MaterialIcon from './MaterialIcon.svelte';
  export let pause = false;
  export let disabled = false;
  export let label = 'Reproducir';
</script>

<button class="phone-play-round" {disabled} aria-label={pause ? 'Pausar' : label} on:click><MaterialIcon name={pause ? 'pause' : 'play_arrow'} size={32} /></button>

<style>
  .phone-play-round{width:56px;height:56px;flex:none;display:grid;place-items:center;border-radius:50%;background:#c4a3ff;color:#000}
  .phone-play-round:disabled{background:#eeeeee1f;color:#eeeeee61}
</style>
