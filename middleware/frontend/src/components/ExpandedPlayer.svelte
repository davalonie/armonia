<script>
  import MaterialIcon from './MaterialIcon.svelte';
  import {mobile} from '../lib/native.js';
  import {
    currentTrack, playing, shuffleOn, repeatMode, playbackProgress,
    next, prev, togglePlayPause, toggleShuffle, toggleRepeat, seekFraction,
    trackArtUrl, isPreview, playbackState, sleepTimer,
  } from '../lib/stores/playerStore.js';
  import { expandedPlayerOpen, queuePanelOpen } from '../lib/stores/uiStore.js';
  import { songMenu, phoneDownloadItem, addToPlaylist } from '../lib/trackActions.js';
  import { showContextMenu } from '../lib/stores/contextMenuStore.js';
  import { showToast } from '../lib/stores/toastStore.js';
  import { deleteTrack } from '../lib/api.js';
  import { command } from '../lib/stores/nativePlayback.js';
  import { fmtTime } from '../lib/util.js';
  import Marquee from './Marquee.svelte';
  import {openLibraryArtist} from '../lib/stores/viewStore.js';
  import DownloadDialog from './DownloadDialog.svelte';
  import {searchSource} from '../lib/searchSource.js';
  import {trackJob} from '../lib/jobs.js';
  let downloadTrack=null;
  import SaveButton from './SaveButton.svelte';
  import {trackSwipe} from '../lib/trackSwipe.js';
  // A sideways swipe on the cover changes song, as in the app: the cover follows the finger (trackSwipe).
  // Pulling down follows the finger and closes as PlayerPane does (pullDismiss); only on the phone.
  import {pullDismiss} from '../lib/pullDismiss.js';
  let pullY = 0;
  $: if (!$expandedPlayerOpen) pullY = 0;
  const closeByPull = () => { pullY = 0; expandedPlayerOpen.set(false); };
  // Compose's tween(300) eases with FastOutSlowInEasing.
  const EASE = 'cubic-bezier(.4,0,.2,1)';

  $: track = $currentTrack;
  $: preview = track ? isPreview(track) : false;
  $: artUrl = track && (!mobile || $expandedPlayerOpen) ? trackArtUrl(track, mobile ? 1024 : 512) : '';
  $: progress = $playbackProgress.duration
    ? ($playbackProgress.currentTime / $playbackProgress.duration) * 100
    : 0;

  // As SeekBar in the app: what is already loaded, in a lighter stretch under the position.
  $: buffered = $playbackProgress.duration
    ? Math.min(100, Math.max(0, ($playbackProgress.buffered || 0) / $playbackProgress.duration * 100)) : 0;

  function handleProgressClick(e) {
    const rect = e.currentTarget.getBoundingClientRect();
    seekFraction((e.clientX - rect.left) / rect.width);
  }

  let dotsBtn, timerDialog;
  async function setTimer(minutes) {
    try { const result=await mobile.command({action:'sleep', minutes}); sleepTimer.set(result.sleep); timerDialog.close(); }
    catch(e) { showToast(e.message,'error'); }
  }
  function openDots() {
    if (!track) return;
    const selected = track;
    const deleteFile = async () => {
      if (!confirm(`¿Eliminar el archivo de «${selected.title}» de la biblioteca? No se puede deshacer.`)) return;
      // On the phone the native player is closed first, as the Kotlin app did: it must not keep playing a deleted file.
      if (mobile) { await command('close'); expandedPlayerOpen.set(false); }
      try { await deleteTrack(selected.id); expandedPlayerOpen.set(false); }
      catch (err) { showToast(`No se pudo eliminar: ${err.message}`, 'error'); }
    };
    const timer = 'Temporizador de apagado'+($sleepTimer.atEnd || $sleepTimer.endsAt?' (activo)':'');
    const download = selected._musicTrack?.source==='youtube';
    if (mobile) return phoneMenu(selected, deleteFile, timer, download);
    void songMenu(dotsBtn, selected, {extra: [
      { label: 'Ver la cola', icon: 'ph ph-list', action: () => queuePanelOpen.set(true) },
      ...(preview ? [] : [null, { label: 'Eliminar archivo de la biblioteca', icon: 'ph ph-trash', danger: true, action: deleteFile }]),
    ]});
  }
  // The app's player menu (ExpandedPlayerScreen): its own short list, without the song's name or stars.
  function phoneMenu(selected, deleteFile, timer, download) {
    const canSave = !String(selected.id).startsWith('external|');
    showContextMenu(dotsBtn, [
      {label: 'Ver la cola', micon: 'queue_music', action: () => queuePanelOpen.set(true)},
      ...(canSave ? [{label: 'Añadir a una playlist', micon: 'playlist_add', action: () => addToPlaylist(selected)}] : []),
      ...(!preview && selected.artistId ? [{label: 'Ver artista', micon: 'person', action: () => {expandedPlayerOpen.set(false); openLibraryArtist(selected.artistId, selected.artist);}}] : []),
      ...(download ? [{label: 'Descargar a la biblioteca', micon: 'download', action: () => downloadTrack = selected}] : []),
      ...(!preview ? [phoneDownloadItem(selected, {DOWNLOADING: 'Descargando en el telefono… (toca para cancelar)'})] : []),
      {label: timer, micon: 'bedtime', action: () => timerDialog.showModal()},
      ...(!preview ? [{label: 'Eliminar archivo de la biblioteca', micon: 'delete', action: deleteFile}] : []),
    ]);
  }
  const repeatLabels = {off: 'Repeticion desactivada', all: 'Repetir la cola', one: 'Repetir esta cancion'};
</script>

{#if downloadTrack}
  <DownloadDialog open={true} videoId={downloadTrack._musicTrack.source_id} artist={downloadTrack.artist} title={downloadTrack.title} album={downloadTrack.album || ''} source={searchSource()} on:close={()=>downloadTrack=null} on:download={e=>trackJob(e.detail.jobId,e.detail.artist,e.detail.title)} />
{/if}
{#if mobile}
  <dialog bind:this={timerDialog} class="bg-armonia-surface text-armonia-text rounded-2xl p-5 w-72 backdrop:bg-black/70" aria-label="Temporizador de apagado">
    <h2 class="font-semibold">Temporizador de apagado</h2>
    <p class="text-sm text-armonia-muted my-2">{$sleepTimer.atEnd?'Se detendrá al terminar esta canción.':$sleepTimer.endsAt?'Se detendrá a las '+new Date($sleepTimer.endsAt).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}):'Detener la reproducción tras'}</p>
    {#each [15,30,45,60] as minutes}<button class="block p-2" on:click={()=>setTimer(minutes)}>{minutes} minutos</button>{/each}
    <button class="block p-2" on:click={()=>setTimer(null)}>Al terminar esta canción</button>
    {#if $sleepTimer.atEnd || $sleepTimer.endsAt}<button class="block p-2" on:click={()=>setTimer(0)}>Desactivar</button>{/if}
    <button class="block p-2" on:click={()=>timerDialog.close()}>Cerrar</button>
  </dialog>
{/if}

<div
  use:pullDismiss={{enabled: mobile && $expandedPlayerOpen, onPull: y => pullY = y, onDismiss: closeByPull, ignore: 'input,[role=slider],dialog'}}
  class="expanded-player fixed inset-0 z-150 flex flex-col pointer-events-none transition-transform duration-300 ease-in-out overflow-hidden"
  style:transform={$expandedPlayerOpen ? (pullY ? `translateY(${pullY}px)` : 'translateY(0)') : 'translateY(100%)'}
  style:transition={mobile ? (pullY ? 'none' : `transform 300ms ${EASE}`) : null}
  style:touch-action={mobile ? 'none' : null}
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
        <MaterialIcon name="more_vert" />
      </button>
    </div>

    <!-- Album art -->
    <div class="player-cover flex-1 flex items-center justify-center py-4 min-h-0 touch-pan-y" use:trackSwipe>
      {#if track}
        {#if mobile}
          <div class="cover-frame">{#if artUrl}{#key artUrl}<img draggable="false" src={artUrl} alt="" class="object-cover" on:error={e=>e.currentTarget.hidden=true}>{/key}{/if}</div>
        {:else}
        <img draggable="false" src={artUrl} alt="" class="w-full max-w-sm aspect-square rounded-xl shadow-[0_20px_60px_rgba(0,0,0,0.6)] object-cover">
        {/if}
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
      {#if mobile}
        <!-- The app's SeekBar: a 4 dp line in three layers (white 22 %, loaded 38 %, played) and a 12 dp thumb. -->
        <!-- svelte-ignore a11y-click-events-have-key-events -->
        <div class="seek" role="slider" tabindex="-1" aria-label="Posicion en la cancion" aria-valuemin="0" aria-valuemax="100"
          aria-valuenow={Math.round(progress)} on:click={handleProgressClick}>
          <span class="seek-track">
            {#if buffered > progress}<span class="seek-loaded" style:width="{buffered}%"></span>{/if}
            <span class="seek-played" style:width="{progress}%"></span>
          </span>
          <span class="seek-thumb" style:left="{progress}%"></span>
        </div>
      {:else}
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
      {/if}
      <div class="flex justify-between text-xs text-armonia-muted" class:seek-times={mobile}>
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

<style>
  /* Phone only (the markup exists only there): PlayerPane's SeekBar. */
  .seek{position:relative;display:flex;align-items:center;height:44px;cursor:pointer}
  .seek-track{position:relative;flex:1;height:4px;border-radius:2px;background:#ffffff38;overflow:hidden}
  .seek-loaded,.seek-played{position:absolute;inset:0 auto 0 0;border-radius:2px}
  .seek-loaded{background:#ffffff61}
  .seek-played{background:#fff}
  .seek-thumb{position:absolute;top:50%;width:12px;height:12px;margin:-6px 0 0 -6px;border-radius:50%;background:#fff;pointer-events:none}
  .seek-times{margin-top:-6px}
</style>
