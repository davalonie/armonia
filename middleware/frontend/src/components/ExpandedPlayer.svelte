<script>
  import {
    currentTrack, playing, shuffleOn, repeatMode, playbackProgress,
    next, prev, togglePlayPause, toggleShuffle, toggleRepeat, seekFraction,
    trackArtUrl, isPreview, playbackState,
  } from '../lib/stores/playerStore.js';
  import { expandedPlayerOpen, queuePanelOpen } from '../lib/stores/uiStore.js';
  import { songMenu } from '../lib/trackActions.js';
  import { showToast } from '../lib/stores/toastStore.js';
  import { showPlaylistPicker } from '../lib/stores/playlistPickerStore.js';
  import { deleteTrack } from '../lib/api.js';
  import { fmtTime } from '../lib/util.js';
  import Marquee from './Marquee.svelte';
  import SaveButton from './SaveButton.svelte';
  // A sideways swipe on the cover changes song, as in the app.
  let swipe = null;
  function swipeStart(e) { swipe = {x: e.clientX, y: e.clientY}; }
  function swipeEnd(e) {
    if (!swipe) return;
    const dx = e.clientX - swipe.x, dy = e.clientY - swipe.y; swipe = null;
    if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) dx < 0 ? next() : prev();
  }

  $: track = $currentTrack;
  $: preview = track ? isPreview(track) : false;
  $: artUrl = track ? trackArtUrl(track, 512) : '';
  $: progress = $playbackProgress.duration
    ? ($playbackProgress.currentTime / $playbackProgress.duration) * 100
    : 0;

  function handleProgressClick(e) {
    const rect = e.currentTarget.getBoundingClientRect();
    seekFraction((e.clientX - rect.left) / rect.width);
  }

  let dotsBtn;
  function openDots() {
    if (!track) return;
    const selected = track;
    void songMenu(dotsBtn, selected, {extra: [
      { label: 'Ver la cola', icon: 'ph ph-list', action: () => queuePanelOpen.set(true) },
      ...(preview ? [] : [null, {
        label: 'Eliminar archivo de la biblioteca', icon: 'ph ph-trash', danger: true,
        action: async () => {
          if (!confirm(`¿Eliminar el archivo de «${selected.title}» de la biblioteca? No se puede deshacer.`)) return;
          try { await deleteTrack(selected.id); expandedPlayerOpen.set(false); }
          catch (err) { showToast(`No se pudo eliminar: ${err.message}`, 'error'); }
        },
      }]),
    ]});
  }
  const repeatLabels = {off: 'Repeticion desactivada', all: 'Repetir la cola', one: 'Repetir esta cancion'};
</script>

<div
  class="fixed inset-0 z-150 flex flex-col pointer-events-none transition-transform duration-300 ease-in-out overflow-hidden"
  style:transform={$expandedPlayerOpen ? 'translateY(0)' : 'translateY(100%)'}
  style:pointer-events={$expandedPlayerOpen ? 'auto' : 'none'}
  style:isolation="isolate"
  inert={!$expandedPlayerOpen}
  role="region"
  aria-label="Reproductor ampliado"
>
  <!-- Opaque base, then the cover as a dark colour wash: the page below never shows through. -->
  <div class="absolute inset-0 z-0" style="background:#121015"></div>
  <div class="absolute inset-0 z-0 bg-cover bg-center scale-125"
       style:background-image={artUrl ? `url('${artUrl}')` : ''}
       style="filter: blur(56px) saturate(1.4) brightness(0.55); will-change: filter;"></div>
  <div class="absolute inset-0 z-0" style="background:linear-gradient(180deg,#12101566 0%,#121015cc 62%,#121015 100%)"></div>

  <!-- Content -->
  <div class="relative z-10 flex flex-col h-full w-full max-w-lg mx-auto px-6" style="padding-top: env(safe-area-inset-top, 0px); transform: translateZ(0);">
    <!-- Top bar -->
    <div class="flex items-center justify-between py-5 shrink-0">
      <button
        aria-label="Cerrar reproductor ampliado"
        on:click={() => expandedPlayerOpen.set(false)}
        class="w-10 h-10 flex items-center justify-center text-armonia-muted hover:text-white transition-colors rounded-full hover:bg-white/10"
      >
        <i class="ph ph-caret-down text-2xl"></i>
      </button>
      <p class="flex flex-col items-center min-w-0 px-2 text-center" aria-live="polite">
        <span class="text-[11px] tracking-widest text-white/70 uppercase">{track?._auto ? 'Continuacion automatica' : track?._from ? 'Reproduciendo desde' : 'Reproduciendo'}</span>
        {#if track?._auto || track?._from}<span class="text-sm font-semibold truncate max-w-[60vw]">{track._auto ? 'Musica similar' : track._from}</span>{/if}
      </p>
      <button
        aria-label="Opciones de la cancion"
        bind:this={dotsBtn}
        on:click={openDots}
        class="w-10 h-10 flex items-center justify-center text-armonia-muted hover:text-white transition-colors rounded-full hover:bg-white/10"
      >
        <i class="ph ph-dots-three-vertical text-2xl"></i>
      </button>
    </div>

    <!-- Album art -->
    <div class="flex-1 flex items-center justify-center py-4 min-h-0 touch-pan-y" on:pointerdown={swipeStart} on:pointerup={swipeEnd} on:pointercancel={() => swipe = null}>
      {#if track}
        <img draggable="false" src={artUrl} alt="" class="w-full max-w-sm aspect-square rounded-xl shadow-[0_20px_60px_rgba(0,0,0,0.6)] object-cover">
      {/if}
    </div>

    <!-- Track info + like -->
    <div class="flex items-center gap-4 mt-6 mb-5 shrink-0">
      <div class="flex-1 min-w-0">
        <Marquee text={track?.title ?? '—'} cls="text-2xl font-bold" />
        <div class="mt-1">
          <Marquee text={track?.artist ?? '—'} cls="text-white/70 text-lg" />
        </div>
        {#if $playbackState === 'error'}<p class="text-sm text-red-300 mt-1" role="alert">No se puede reproducir esta cancion. Puedes pasar a la siguiente.</p>{/if}
      </div>
      <SaveButton {track} size="lg" />
    </div>

    <!-- Progress -->
    <div class="shrink-0 mb-1">
      <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
      <div
        class="w-full h-1.5 bg-white/15 rounded-full cursor-pointer group mb-2"
        on:click={handleProgressClick}
      >
        <div
          class="h-full bg-armonia-accent rounded-full relative group-hover:bg-armonia-accentHover transition-colors"
          style:width="{progress}%"
        >
          <div class="absolute right-0 top-1/2 -translate-y-1/2 -mr-2 w-4 h-4 bg-white rounded-full shadow-sm opacity-0 group-hover:opacity-100 transition-opacity"></div>
        </div>
      </div>
      <div class="flex justify-between text-xs text-armonia-muted">
        <span>{fmtTime($playbackProgress.currentTime)}</span>
        <span>{fmtTime($playbackProgress.duration)}</span>
      </div>
    </div>

    <!-- Controls -->
    <div class="flex items-center justify-between shrink-0 mt-5 mb-4">
      <button
        aria-label="Reproduccion aleatoria" aria-pressed={$shuffleOn}
        on:click={toggleShuffle}
        class="w-11 h-11 flex items-center justify-center transition-colors rounded-full hover:bg-white/10 {$shuffleOn ? 'text-armonia-accent' : 'text-armonia-muted hover:text-white'}"
      >
        <i class="ph ph-shuffle text-2xl"></i>
      </button>
      <button aria-label="Cancion anterior" on:click={prev} class="w-11 h-11 flex items-center justify-center text-armonia-muted hover:text-white transition-colors">
        <i class="ph-fill ph-skip-back text-3xl"></i>
      </button>
      <button
        aria-label={$playing ? 'Pausar' : 'Reproducir audio'}
        on:click={togglePlayPause}
        class="w-[72px] h-[72px] rounded-full bg-white text-armonia-bg flex items-center justify-center hover:scale-105 transition-transform shadow-xl"
      >
        {#if $playbackState === 'loading'}<i class="ph ph-circle-notch text-3xl animate-spin" aria-label="Cargando"></i>
        {:else}<i class="ph-fill {$playing ? 'ph-pause' : 'ph-play'} text-3xl"></i>{/if}
      </button>
      <button aria-label="Cancion siguiente" on:click={next} class="w-11 h-11 flex items-center justify-center text-armonia-muted hover:text-white transition-colors">
        <i class="ph-fill ph-skip-forward text-3xl"></i>
      </button>
      <button
        aria-label={repeatLabels[$repeatMode]} title={repeatLabels[$repeatMode]}
        on:click={toggleRepeat}
        class="w-11 h-11 flex items-center justify-center transition-colors rounded-full hover:bg-white/10 {$repeatMode !== 'off' ? 'text-armonia-accent' : 'text-armonia-muted hover:text-white'}"
      >
        <i class="ph {$repeatMode === 'one' ? 'ph-repeat-once' : 'ph-repeat'} text-2xl"></i>
      </button>
    </div>
    <div class="flex items-center justify-end shrink-0 mb-6" style="padding-bottom: env(safe-area-inset-bottom, 0px)">
      <button aria-label="Ver la cola" on:click={() => queuePanelOpen.set(true)}
        class="h-11 px-3 flex items-center gap-2 text-white/80 hover:text-white rounded-full hover:bg-white/10 transition-colors">
        <i class="ph ph-list text-2xl"></i><span class="text-sm">Cola</span>
      </button>
    </div>
  </div>
</div>
