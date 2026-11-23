<script>
  import FastScroll from './FastScroll.svelte';
  import {songLabels} from '../lib/fastScroll.js';
  import ShuffleToggle from './ShuffleToggle.svelte';
  import {
    currentTrack, currentIndex, queue, playing,
    playQueue, playNext, togglePlayPause, shuffleOn, firstShuffled,
    trackArtUrl,
  } from '../lib/stores/playerStore.js';
  import { library as libApi, deleteTrack as apiDeleteTrack, coverArtUrl, streamUrl } from '../lib/api.js';
  import { fmtDuration } from '../lib/util.js';
  import { songMenu } from '../lib/trackActions.js';
  import { showPlaylistPicker } from '../lib/stores/playlistPickerStore.js';
  import {replaceLocal} from '../lib/playlistEdits.js';
  import {showToast} from '../lib/stores/toastStore.js';
  import Marquee from './Marquee.svelte';

  export let songs = [];
  export let allStarred = false;
  export let playlistId = null;
  export let onRefresh = null;

  export let playlistName = '';
  /** Fast-scroll labels for `songs` as given (the parent's order); without them, the playlist's position. */
  export let scrollLabels = null;
  /** False when the screen above already has its own search, order and play controls (Canciones, favoritos). */
  export let tools = true;
  let listEl;
  $: labels = sort !== 'original' ? songLabels(rows.map(r => r.song), sort)
    : scrollLabels && rows.length === songs.length ? scrollLabels : rows.map(r => String(r.i + 1));
  let toolsOpen=false, filter='', sort='original', touchStart=null;
  $: rows=songs.map((song,i)=>({song,i})).filter(({song})=>`${song.title} ${song.artist}`.toLocaleLowerCase().includes(filter.toLocaleLowerCase()));
  $: if(sort!=='original') rows=[...rows].sort((a,b)=>String(a.song[sort]||'').localeCompare(String(b.song[sort]||'')));
  function reveal(e){if(touchStart!==null && e.changedTouches[0].clientY-touchStart>55)toolsOpen=true;touchStart=null;}
  let selectMode = false;
  let selected = new Set();
  let starredOverrides = {};

  // Reset selection when songs list changes
  $: songs, resetSelect();
  function resetSelect() { selectMode = false; selected = new Set(); }

  function isStarred(song) {
    return song.id in starredOverrides ? starredOverrides[song.id] : (allStarred || !!song.starred);
  }

  async function toggleStar(song, e) {
    e?.stopPropagation();
    const was = isStarred(song);
    starredOverrides = { ...starredOverrides, [song.id]: !was };
    try {
      await libApi(was ? 'unstar' : 'star', { id: song.id });
    } catch {
      starredOverrides = { ...starredOverrides, [song.id]: was };
    }
  }

  // With shuffle on, Play starts from a random song of the list (as in the app); in order otherwise.
  function playFromHeader() {
    const i = $shuffleOn ? firstShuffled(songs.length) : 0;
    handleRowClick({}, songs[i], i);
  }

  function handleRowClick(e, song, i) {
    if (selectMode) {
      toggleSelect(i);
      return;
    }
    if ($currentTrack?.id === song.id && $currentIndex === i && $queue.length === songs.length && $queue.every((t,n)=>t.id===songs[n].id) && (!playlistId || $currentTrack?._playlist?.id===playlistId)) {
      togglePlayPause();
      return;
    }
    playQueue(songs.map(t=>playlistId?{...t,_playlist:{kind:'local',id:playlistId}}:t), i);
  }

  function toggleSelect(i) {
    const s = new Set(selected);
    if (s.has(i)) s.delete(i); else s.add(i);
    selected = s;
  }

  function enterSelectMode(i = null) {
    selectMode = true;
    selected = i !== null ? new Set([i]) : new Set();
  }
  function exitSelectMode() { selectMode = false; selected = new Set(); }

  function getSelectedIds() { return [...selected].map(i => songs[i].id); }

  async function bulkDelete() {
    const ids = getSelectedIds();
    if (!ids.length || !confirm(`Delete ${ids.length} track${ids.length > 1 ? 's' : ''}? This cannot be undone.`)) return;
    const indices = [...selected];
    for (const idx of indices) {
      try { await apiDeleteTrack(songs[idx].id); } catch {}
    }
    exitSelectMode();
    onRefresh?.();
  }

  async function removePositions(indices){
    try{await replaceLocal(playlistId,songs.map(s=>s.id),songs.filter((_,i)=>!indices.has(i)).map(s=>s.id));exitSelectMode();onRefresh?.();}
    catch(e){showToast(e.message);}
  }
  async function bulkRemoveFromPlaylist(){await removePositions(selected);}

  let downloadOpen=false;
  function openDots(e, song, i) {
    e.stopPropagation();
    void songMenu(e.currentTarget, {...song, starred: isStarred(song) ? (song.starred || true) : undefined}, {
      onChange: () => onRefresh?.(),
      extra: [
        { label: 'Seleccionar', icon: 'ph ph-check-square', action: () => enterSelectMode(i) },
        // Removing from a list never deletes the file; deleting the file is a separate, confirmed action.
        ...(playlistId ? [{ label: 'Quitar de esta playlist', icon: 'ph ph-minus-circle', action: () => removePositions(new Set([i])) }] : []),
        null,
        {
          label: 'Eliminar archivo de la biblioteca', icon: 'ph ph-trash', danger: true,
          action: async () => {
            if (!confirm(`¿Eliminar el archivo de «${song.title}» de la biblioteca? No se puede deshacer.`)) return;
            try { await apiDeleteTrack(song.id); onRefresh?.(); }
            catch (err) { showToast(`No se pudo eliminar: ${err.message}`, 'error'); }
          },
        },
      ],
    });
  }

</script>

{#if tools}<div role="group" aria-label="Controles de playlist" class="playlist-tools" on:touchstart={e=>touchStart=e.touches[0].clientY} on:touchend={reveal}>
  {#if toolsOpen}<div class="actions"><input aria-label="Buscar en la lista" placeholder="Buscar en la lista" bind:value={filter}><label>Ordenar <select bind:value={sort}><option value="original">Orden de la playlist</option><option value="title">Titulo</option><option value="artist">Artista</option></select></label></div>{/if}
  {#if playlistName}<h2 class="text-3xl font-semibold my-4">{playlistName}</h2>{/if}
  <div class="actions"><span>{songs.length} canciones</span><button aria-expanded={toolsOpen} on:click={()=>toolsOpen=!toolsOpen}>Buscar y ordenar</button>
  <button class="playlist-play" disabled={!songs.length} on:click={playFromHeader}>▶ Reproducir</button>
  <ShuffleToggle size="sm" /><button disabled={!songs.length} aria-expanded={downloadOpen} on:click={()=>downloadOpen=!downloadOpen}>↓ Descargar</button></div>
  {#if downloadOpen}<section aria-label="Descargar canciones" class="music-card max-h-56 overflow-auto"><p>Descarga los archivos que quieras al dispositivo. Para conservar toda la playlist offline, usa Android.</p>{#each songs as song,i}<a class="block p-3" href={streamUrl(song.id)} download={song.title}>{i+1}. Descargar {song.title}</a>{/each}</section>{/if}
</div>{/if}

{#if selectMode}
  <div class="flex items-center gap-2 pb-2 px-1 overflow-x-auto no-scrollbar flex-nowrap">
    <span class="text-sm text-armonia-muted mr-1">{selected.size} selected</span>
    <button
      on:click={() => showPlaylistPicker(songs.filter((_,i)=>selected.has(i)), exitSelectMode)}
      disabled={selected.size === 0}
      class="flex items-center gap-1.5 px-3 py-1.5 bg-white/10 hover:bg-white/20 rounded-lg text-xs font-medium transition-colors disabled:opacity-40"
    >
      <i aria-hidden="true" class="ph ph-music-notes-plus text-sm"></i> Add to playlist
    </button>
    {#if playlistId}
      <button
        on:click={bulkRemoveFromPlaylist}
        disabled={selected.size === 0}
        class="flex items-center gap-1.5 px-3 py-1.5 bg-white/10 hover:bg-white/20 rounded-lg text-xs font-medium transition-colors disabled:opacity-40"
      >
        <i aria-hidden="true" class="ph ph-minus-circle text-sm"></i> Remove selected
      </button>
    {/if}
    <button
      on:click={bulkDelete}
      disabled={selected.size === 0}
      class="flex items-center gap-1.5 px-3 py-1.5 bg-red-500/20 hover:bg-red-500/30 text-red-400 rounded-lg text-xs font-medium transition-colors disabled:opacity-40"
    >
      <i aria-hidden="true" class="ph ph-trash text-sm"></i> Eliminar
    </button>
    <button
      on:click={exitSelectMode}
      class="ml-auto flex items-center gap-1.5 px-3 py-1.5 bg-white/5 hover:bg-white/10 rounded-lg text-xs font-medium transition-colors"
    >Cancelar</button>
  </div>
{/if}

<!-- Track rows -->
<FastScroll {labels} list={listEl} />
<div class="flex flex-col gap-1" bind:this={listEl}>
  {#each rows as {song,i} (i)}
    {@const isActive = $currentTrack?.id === song.id}
    {@const starred = song.id in starredOverrides ? starredOverrides[song.id] : (allStarred || !!song.starred)}
    <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
    <div
      class="group flex items-center gap-3 p-3 rounded-xl hover:bg-white/5 transition-all cursor-pointer"
      on:click={e => handleRowClick(e, song, i)}
      role="button" tabindex="0" aria-label={`Reproducir ${song.title}`}
      on:keydown={e=>{if(e.target===e.currentTarget && ['Enter',' '].includes(e.key)){e.preventDefault();handleRowClick(e,song,i);}}}
    >
      <!-- Checkbox (select mode) -->
      {#if selectMode}
        <div class="shrink-0 w-5 flex items-center justify-center">
          <input
            type="checkbox"
            checked={selected.has(i)}
            on:change={() => toggleSelect(i)}
            on:click|stopPropagation
            class="w-4 h-4 rounded-sm accent-armonia-accent cursor-pointer"
          >
        </div>
      {/if}

      <!-- Art / now-playing indicator -->
      <div class="relative w-12 h-12 rounded-md overflow-hidden shrink-0 bg-armonia-surface">
        <span aria-hidden="true" class="absolute inset-0 grid place-items-center text-armonia-accent text-2xl">♫</span>{#if song.coverArt}<img src={coverArtUrl(song.coverArt, 64)} alt="" loading="lazy" class="relative w-full h-full object-cover" on:error={e=>e.currentTarget.style.visibility='hidden'}>{/if}
        <!-- Hover play/pause overlay -->
        <div class="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 flex items-center justify-center transition-opacity {isActive ? 'opacity-100' : ''}">
          <i aria-hidden="true" class="ph-fill {isActive && $playing ? 'ph-pause' : 'ph-play'} text-white text-lg pointer-events-none"></i>
        </div>
        <!-- Now-playing animated bars -->
        {#if isActive}
          <div class="absolute inset-0 bg-black/60 flex items-end justify-center gap-[3px] pb-[9px] {$playing ? '' : 'opacity-60'}">
            <span class="block w-[3px] bg-armonia-accent rounded-xs origin-bottom {$playing ? 'animate-bar1' : ''}" style="height:12px"></span>
            <span class="block w-[3px] bg-armonia-accent rounded-xs origin-bottom {$playing ? 'animate-bar2' : ''}" style="height:12px"></span>
            <span class="block w-[3px] bg-armonia-accent rounded-xs origin-bottom {$playing ? 'animate-bar3' : ''}" style="height:12px"></span>
          </div>
        {/if}
      </div>

      <!-- Title / artist -->
      <div class="flex-1 min-w-0 pr-2">
        <Marquee text={song.title ?? '—'} cls="font-medium" />
        <Marquee text="{song.artist ?? '—'} · {fmtDuration(song.duration)}" cls="text-sm text-armonia-muted" />
      </div>

      <!-- Star button -->
      <button
        class="w-9 h-9 rounded-full flex items-center justify-center hover:bg-white/10 transition-all opacity-100 md:opacity-0 group-hover:opacity-100 shrink-0"
        title={starred ? 'Unlike' : 'Like'}
        on:click={e => toggleStar(song, e)}
      >
        <i aria-hidden="true" class="{starred ? 'ph-fill ph-heart text-armonia-accent' : 'ph ph-heart text-armonia-muted'} text-lg pointer-events-none"></i>
      </button>

      <!-- Dots menu button -->
      <button
        class="w-9 h-9 rounded-full flex items-center justify-center hover:bg-white/10 transition-all opacity-100 md:opacity-0 group-hover:opacity-100 shrink-0"
        title="Opciones de cancion" aria-label={`Opciones de ${song.title}`}
        on:click={e => openDots(e, song, i)}
      >
        <i aria-hidden="true" class="ph ph-dots-three-vertical text-armonia-muted text-lg pointer-events-none"></i>
      </button>
    </div>
  {/each}
</div>

<style>
.playlist-tools{margin:1rem 0 1.25rem}.playlist-tools .actions{display:flex;flex-wrap:wrap;align-items:center;gap:.65rem;margin:.8rem 0}.playlist-tools button{padding:.65rem 1rem;border:1px solid #ffffff30;border-radius:2rem;min-height:44px;background:#ffffff08}.playlist-tools button:hover{background:#ffffff16}.playlist-tools button.playlist-play{background:#c4a3ff;color:#18101f;border-color:#c4a3ff;font-weight:650}.playlist-tools button:disabled{opacity:.45}.playlist-tools input,.playlist-tools select{border:1px solid #ffffff30;border-radius:.6rem;padding:.65rem;background:#211c29;max-width:100%}.playlist-tools label{display:flex;gap:.5rem;align-items:center}.playlist-tools .actions>span{color:#aaa3b3;margin-right:.5rem}.playlist-tools .music-card{padding:1rem;border:1px solid #ffffff20;border-radius:.8rem;margin:1rem 0}
</style>
