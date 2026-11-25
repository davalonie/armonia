<script>
  // The app's Snackbar (material3 1.4.0, the SnackbarHost of MainScreen's Scaffold), on the phone only.
  // Placed right above the mini player, or above the bottom bar without one; under the expanded player,
  // the queue, menus and dialogs, which cover it as in the app; over «Añadir canciones», which in the app
  // is a screen of its own with its Snackbar at the bottom. The keyboard covers it, as in the app.
  import {onDestroy} from 'svelte';
  import {phoneSnackbar} from '../lib/stores/toastStore.js';
  import {springAt, OPACITY, SCALE, HIDDEN_SCALE, SETTLED} from '../lib/phoneSnackbar.js';

  // Each notice keeps showing while it fades out under the next one.
  let shown = [], frame = 0;
  const target = e => e.visible ? 1 : 0;
  function animate(now) {
    frame = 0;
    for (const e of shown) {
      // The frame may have started a moment before the notice arrived.
      const t = Math.max(0, now - e.since) / 1000;
      e.opacity = springAt(e.from.opacity, target(e), t, OPACITY);
      e.scale = springAt(e.from.scale, e.visible ? 1 : HIDDEN_SCALE, t, SCALE);
      e.done = Math.abs(e.opacity - target(e)) < SETTLED && Math.abs(e.scale - (e.visible ? 1 : HIDDEN_SCALE)) < SETTLED;
      if (e.done) { e.opacity = target(e); e.scale = e.visible ? 1 : HIDDEN_SCALE; }
    }
    shown = shown.filter(e => e.visible || !e.done);
    if (shown.some(e => !e.done)) frame = requestAnimationFrame(animate);
  }
  const retarget = (e, visible, now) => Object.assign(e, {visible, since: now, from: {opacity: e.opacity, scale: e.scale}, done: false});
  const unsubscribe = phoneSnackbar.subscribe(item => {
    const now = performance.now();
    for (const e of shown) if (e.visible && e.item !== item) retarget(e, false, now);
    if (item && !shown.some(e => e.item === item)) shown = [...shown, retarget({item, opacity: 0, scale: HIDDEN_SCALE}, true, now)];
    if (!frame) frame = requestAnimationFrame(animate);
  });
  onDestroy(() => { unsubscribe(); cancelAnimationFrame(frame); });

  // OneRowSnackbar: 48 dp for one line of text, 68 dp for two (a line is 20 px plus 6 px above and below).
  function lines(node) {
    const measure = () => node.closest('.snackbar')?.classList.toggle('two-lines', node.offsetHeight > 40);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return {destroy: () => observer.disconnect()};
  }
</script>

<div class="phone-snackbar-host">
  {#each shown as e (e.item.id)}
    <div class="snackbar" role="status" aria-live="polite" inert={!e.visible} style:opacity={e.opacity} style:transform="scale({e.scale})">
      <p use:lines>{e.item.message}</p>
      {#if e.item.action}<button type="button" on:click={() => phoneSnackbar.act(e.item.id)}>Deshacer</button>{/if}
    </div>
  {/each}
</div>

<style>
  /* Scaffold puts the host right on top of its bottomBar (mini player + navigation bar); the
     Snackbar keeps 12 dp all around inside it. Touches on that margin go through. */
  .phone-snackbar-host{position:fixed;left:0;right:0;z-index:140;display:grid;padding:12px;pointer-events:none;
    bottom:calc(var(--mob-nav-h) + env(safe-area-inset-bottom,0px))}
  :global(body.player-visible) .phone-snackbar-host{bottom:calc(var(--mob-nav-h) + env(safe-area-inset-bottom,0px) + var(--mob-mini-h))}
  :global(body:has(dialog.add-songs[open])) .phone-snackbar-host{bottom:env(safe-area-inset-bottom,0px);z-index:260}
  /* SnackbarTokens: inverse surface, 4 dp corners, elevation level 3; supporting text bodyMedium,
     action labelLarge in inverse primary (the app's dark scheme: #E6E0E9, #322F35, #6750A4). */
  .snackbar{grid-area:1/1;align-self:end;display:flex;align-items:center;min-height:48px;max-width:600px;width:100%;box-sizing:border-box;
    margin:0 auto;padding:0 8px 0 16px;border-radius:4px;background:#e6e0e9;color:#322f35;pointer-events:auto;transform-origin:center;
    font-family:var(--font-sans);
    /* The elevation shadow, which on this dark background only darkens it by a few levels, drawn without
       blur: a blurred one stalled the WebView for about a second the first time a notice showed. */
    box-shadow:0 0 0 1px rgba(0,0,0,.06),-1px 0 0 0 rgba(0,0,0,.06),-3px 0 0 0 rgba(0,0,0,.06),1px 0 0 0 rgba(0,0,0,.06),
      3px 0 0 0 rgba(0,0,0,.06),0 2px 0 0 rgba(0,0,0,.07),0 6px 0 0 rgba(0,0,0,.11)}
  .snackbar:global(.two-lines){min-height:68px}
  p{flex:1;min-width:0;margin:0 8px 0 0;padding:6px 0;font-size:14px;line-height:20px;letter-spacing:.25px;font-weight:400;overflow-wrap:anywhere}
  /* TextButton: 40 dp high, at least 58 wide, 12 dp at the sides. */
  button{flex:none;min-height:40px;height:40px;min-width:58px;padding:0 12px;border-radius:20px;background:transparent;color:#6750a4;
    font-size:14px;line-height:20px;letter-spacing:.1px;font-weight:500;font-family:inherit}
  button:active{background:rgba(103,80,164,.1)}
</style>
