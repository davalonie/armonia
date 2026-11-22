<script>
  // The shuffle button of a list header, as in the app: the same global switch as the player's. It does not start
  // playing; Play then starts from a random song of the list, and a tapped song plays first with the rest shuffled.
  import {shuffleOn,toggleShuffle} from '../lib/stores/playerStore.js';
  export let size='md';
</script>

<button class="shuffle {size}" class:on={$shuffleOn} aria-pressed={$shuffleOn} aria-label="Aleatorio"
  title={$shuffleOn?'Aleatorio activado':'Aleatorio desactivado'} on:click={toggleShuffle}>
  <i aria-hidden="true" class="ph ph-shuffle"></i>{#if $shuffleOn}<span class="dot" aria-hidden="true"></span>{/if}
</button>

<style>
  .shuffle{position:relative;flex:none;width:44px;height:44px;display:grid;place-items:center;border-radius:50%;font-size:1.5rem;color:var(--color-armonia-muted)}
  .shuffle.sm{width:36px;height:36px;font-size:1.25rem}
  .shuffle:hover{background:#ffffff14;color:#fff}
  .shuffle.on,.shuffle.on:hover{color:var(--color-armonia-accent)}
  .dot{position:absolute;bottom:4px;left:50%;width:5px;height:5px;margin-left:-2.5px;border-radius:50%;background:var(--color-armonia-accent)}
</style>
