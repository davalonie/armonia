<script>
  // The mark of the song that is playing on its cover, as SongRow and QueueSheet draw it: a black veil
  // and, on it, only the bars when it plays or the GraphicEq icon when it is paused.
  import MaterialIcon from './MaterialIcon.svelte';
  import NowPlayingBars from './NowPlayingBars.svelte';
  export let playing = false;
  export let veil = .5;
</script>

<span class="mark" style:background="rgba(0,0,0,{veil})">
  {#if playing}<NowPlayingBars />{:else}<span role="img" aria-label="Sonando"><MaterialIcon name="graphic_eq" size={20} /></span>{/if}
</span>

<style>
  .mark{position:absolute;inset:0;display:grid;place-items:center;border-radius:inherit;color:var(--color-armonia-accent);pointer-events:none}
</style>
