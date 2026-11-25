<script>
  // The app's NowPlayingBars (ui/components/NowPlayingBars.kt): four 3 dp bars, 2 dp apart, each
  // bouncing between 25 % and 100 % of the height in 280 + i·90 ms with FastOutSlowInEasing.
  export let height = 16;
</script>

<span class="bars" style:height="{height}px" aria-hidden="true">
  {#each [0, 1, 2, 3] as i}<i style:animation-duration="{280 + i * 90}ms"></i>{/each}
</span>

<style>
  .bars{display:flex;align-items:flex-end;gap:2px;color:var(--color-armonia-accent)}
  .bars i{display:block;width:3px;height:100%;border-radius:1px;background:currentColor;transform-origin:bottom;
    animation:bounce cubic-bezier(.4,0,.2,1) infinite alternate}
  @keyframes bounce{from{transform:scaleY(.25)}to{transform:scaleY(1)}}
</style>
