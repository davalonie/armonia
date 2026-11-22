<script>
  import {
    currentTrack, playing, shuffleOn, repeatMode, playbackProgress,
    next, prev, togglePlayPause, toggleShuffle, toggleRepeat, seekFraction, closePlayer,
    trackArtUrl,
  } from '../lib/stores/playerStore.js';
  import { expandedPlayerOpen, queuePanelOpen } from '../lib/stores/uiStore.js';
  import { fmtTime } from '../lib/util.js';
  import Marquee from './Marquee.svelte';
  import SaveButton from './SaveButton.svelte';
  // On a phone, as in the app: cover, title, + / ✓ and play, the progress along the bottom, and a sideways swipe
  // changes song. Wider, the full bar stays (previous, next, shuffle, repeat, queue, time), with + / ✓ for the heart.
  let swipe = null, swiped = false;
  function swipeStart(e) { if (e.pointerType !== 'mouse') swipe = {x: e.clientX, y: e.clientY}; swiped = false; }
  function swipeEnd(e) {
    if (!swipe) return;
    const dx = e.clientX - swipe.x, dy = e.clientY - swipe.y; swipe = null;
    if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) { swiped = true; dx < 0 ? next() : prev(); }
  }
  function openExpanded() { if (swiped) { swiped = false; return; } expandedPlayerOpen.set(true); }

  $: track = $currentTrack;
  $: visible = !!track;
  $: progress = $playbackProgress.duration
    ? ($playbackProgress.currentTime / $playbackProgress.duration) * 100
    : 0;

  function handleProgressClick(e) {
    const rect = e.currentTarget.getBoundingClientRect();
    seekFraction((e.clientX - rect.left) / rect.width);
  }
</script>

<div
  id="mini-player"
  class="fixed bottom-0 w-full h-[64px] md:h-[90px] bg-armonia-surface border-t border-white/5 z-50 items-center px-4 md:px-6 gap-4 shadow-[0_-10px_30px_rgba(0,0,0,0.5)] user-select-none {visible ? 'flex' : 'hidden'}"
>
  <!-- Progress bar -->
  <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
  <div class="absolute bottom-0 md:bottom-auto md:top-0 left-0 w-full h-[3px] md:h-1 bg-armonia-bg group cursor-pointer" on:click={handleProgressClick}>
    <div class="h-full bg-armonia-accent group-hover:bg-armonia-accentHover transition-colors relative" style:width="{progress}%">
      <div class="absolute right-0 top-1/2 -translate-y-1/2 w-3 h-3 bg-white rounded-full opacity-0 group-hover:opacity-100 shadow-md"></div>
    </div>
  </div>

  <!-- Vinyl record + tonearm -->
  <button aria-label="Abrir reproductor ampliado" class="md:hidden shrink-0 w-12 h-12 rounded-md overflow-hidden bg-white/5" on:click={() => expandedPlayerOpen.set(true)}>
    {#if track && trackArtUrl(track,96)}<img src={trackArtUrl(track, 96)} alt="" on:error={e=>e.currentTarget.style.visibility='hidden'} class="w-full h-full object-cover">{/if}
  </button>
  <button aria-label="Abrir reproductor ampliado" class="vinyl-wrap shrink-0 relative cursor-pointer hidden md:block" on:click={() => expandedPlayerOpen.set(true)}>
    <!-- Disc -->
    <div class="vinyl-disc" class:spinning={$playing}>
      <!-- Album art label -->
      <div class="vinyl-label">
        {#if track && trackArtUrl(track,96)}<img src={trackArtUrl(track, 96)} alt="" on:error={e=>e.currentTarget.style.visibility='hidden'} class="w-full h-full object-cover">{/if}
      </div>
      <!-- Spindle hole -->
      <div class="vinyl-hole"></div>
    </div>
    <!-- Tonearm -->
    <div
      class="tonearm"
      style="transform-origin: top center; transition: transform 0.4s cubic-bezier(0.34,1.56,0.64,1); transform: {$playing ? 'rotate(24deg)' : 'rotate(-20deg)'};"
    ></div>
  </button>

  <!-- Track info -->
  <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
  <div class="flex-1 min-w-0 cursor-pointer touch-pan-y" on:click={openExpanded} on:pointerdown={swipeStart} on:pointerup={swipeEnd} on:pointercancel={() => swipe = null}>
    <Marquee text={track?.title ?? 'Sin reproducción'} cls="text-sm font-semibold text-white" />
    <Marquee text={track?.artist ?? 'Elige una canción'} cls="text-xs text-armonia-muted" />
  </div>

  <!-- Controls -->
  <div class="flex items-center gap-3 shrink-0">
    <SaveButton {track} />
    <button aria-label="Canción anterior" on:click={prev} class="hidden md:block text-armonia-muted hover:text-white transition-colors">
      <i class="ph-fill ph-skip-back text-xl"></i>
    </button>
    <button aria-label={$playing ? 'Pausar' : 'Reproducir audio'} on:click={togglePlayPause} class="play-btn rounded-full flex items-center justify-center">
      <i class="ph-fill {$playing ? 'ph-pause' : 'ph-play'} text-lg"></i>
    </button>
    <button aria-label="Canción siguiente" on:click={next} class="hidden md:block text-armonia-muted hover:text-white transition-colors">
      <i class="ph-fill ph-skip-forward text-xl"></i>
    </button>
    <button aria-label="Reproducción aleatoria" aria-pressed={$shuffleOn} on:click={toggleShuffle}
      class="hidden md:flex transition-colors {$shuffleOn ? 'text-armonia-accent' : 'text-armonia-muted hover:text-white'}">
      <i class="ph ph-shuffle text-xl"></i>
    </button>
    <button aria-label={`Repetir: ${$repeatMode}`} on:click={toggleRepeat}
      class="hidden md:flex transition-colors {$repeatMode !== 'off' ? 'text-armonia-accent' : 'text-armonia-muted hover:text-white'}">
      <i class="ph {$repeatMode === 'one' ? 'ph-repeat-once' : 'ph-repeat'} text-xl"></i>
    </button>
    <button aria-label="Abrir cola" on:click={() => queuePanelOpen.set(true)}
      class="hidden md:flex text-armonia-muted hover:text-white transition-colors">
      <i class="ph ph-list text-xl"></i>
    </button>
    <span class="hidden md:inline text-sm text-armonia-muted tabular-nums">
      {fmtTime($playbackProgress.currentTime)} / {fmtTime($playbackProgress.duration)}
    </span>
    <button aria-label="Cerrar reproductor" on:click={closePlayer} class="hidden md:block text-armonia-muted hover:text-white transition-colors shrink-0">
      <i class="ph ph-x text-xl"></i>
    </button>
  </div>
</div>

<style>
  /* ── Vinyl wrap ───────────────────────────────── */
  .vinyl-wrap {
    width: 80px;
    height: 68px;
  }

  /* ── Record disc ──────────────────────────────── */
  .vinyl-disc {
    position: absolute;
    left: 0;
    top: 0;
    width: 68px;
    height: 68px;
    border-radius: 50%;
    background: radial-gradient(circle,
      #1c1c1f 0% 29%,
      #4b4b52 29% 31%,
      #2c2c31 31% 39%,
      #4b4b52 39% 41%,
      #2c2c31 41% 48%,
      #4b4b52 48% 50%,
      #2c2c31 50% 100%
    );
    box-shadow:
      0 4px 20px rgba(0, 0, 0, 0.85),
      0 0 0 2px rgba(255, 255, 255, 0.18);
    animation: vinyl-spin 3s linear infinite;
    animation-play-state: paused;
  }

  .vinyl-disc.spinning {
    animation-play-state: running;
  }

  @keyframes vinyl-spin {
    to { transform: rotate(360deg); }
  }

  /* ── Album art label ──────────────────────────── */
  .vinyl-label {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 36px;
    height: 36px;
    border-radius: 50%;
    overflow: hidden;
    background: #09090b;
    box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.1);
  }

  /* ── Spindle hole ─────────────────────────────── */
  .vinyl-hole {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #09090b;
    box-shadow: inset 0 1px 3px rgba(0, 0, 0, 1);
    z-index: 1;
  }

  /* ── Tonearm ──────────────────────────────────── */
  .tonearm {
    position: absolute;
    top: 1px;
    right: 1px;
    width: 3px;
    height: 34px;
    border-radius: 2px;
    background: linear-gradient(to bottom, #a1a1aa 0%, #71717a 65%, #c4a3ff 82%, #8b5cf6 100%);
  }

  /* Pivot head */
  .tonearm::before {
    content: '';
    position: absolute;
    top: -5px;
    left: 50%;
    transform: translateX(-50%);
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: radial-gradient(circle, #d4d4d8 0%, #71717a 100%);
    box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.12), 0 2px 4px rgba(0, 0, 0, 0.6);
  }

  /* ── Play / Pause button ──────────────────────── */
  .play-btn {
    width: 40px;
    height: 40px;
    border: 2px solid #c4a3ff;
    color: #c4a3ff;
    transition: background-color 0.15s ease, color 0.15s ease;
  }

  .play-btn:hover {
    background-color: #c4a3ff;
    color: #09090b;
  }
</style>
