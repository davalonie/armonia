<script>
  import FastScroll from '../components/FastScroll.svelte';
  import {scrollInitial} from '../lib/fastScroll.js';
  import { library as libApi, coverArtUrl } from '../lib/api.js';
  import TrackList from '../components/TrackList.svelte';
  import { playQueue } from '../lib/stores/playerStore.js';

  // Navigation stack: [{ type, id?, label }]
  let stack = [{ type: 'artists', label: 'Artistas' }];
  let loading = true;
  let error = '';

  // View data
  let artists = [];
  let artistFilter = '';
  let artistSort = 'name';
  let artistList;
  $: artistLabels = filteredArtists.map(a => artistSort === 'albums' ? `${a.albumCount || 0} álb.` : scrollInitial(a.name));
  // Artists whose picture could not be loaded show their initial instead of a broken image.
  let noPicture = new Set();
  let albums = [];
  let songs = [];

  $: top = stack[stack.length - 1];
  const fold = text => (text || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  // The filter looks inside whole names only; a name is never split on commas, "y" or "&".
  $: filteredArtists = artists
    .filter(a => !artistFilter || fold(a.name).includes(fold(artistFilter)))
    .sort((a, b) => artistSort === 'albums'
      ? (b.albumCount || 0) - (a.albumCount || 0) || a.name.localeCompare(b.name, 'es')
      : a.name.localeCompare(b.name, 'es'));
  const count = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  $: top, loadCurrent();

  async function loadCurrent() {
    loading = true; error = '';
    try {
      if (top.type === 'artists') await loadArtists();
      else if (top.type === 'artist') await loadArtist(top.id);
      else if (top.type === 'album') await loadAlbum(top.id);
    } catch (e) { error = e.message; }
    finally { loading = false; }
  }

  async function loadArtists() {
    const r = await libApi('getArtists');
    artists = (r.artists?.index || []).flatMap(i => i.artist || []);
    artistFilter = '';
    noPicture = new Set();
  }

  async function loadArtist(id) {
    const r = await libApi('getArtist', { id });
    albums = r.artist?.album || [];
  }

  async function loadAlbum(id) {
    const r = await libApi('getAlbum', { id });
    songs = r.album?.song || [];
  }

  function push(item) { stack = [...stack, item]; }
  function goTo(idx) { stack = stack.slice(0, idx + 1); }
</script>

<div class="w-full max-w-5xl mx-auto p-4 md:p-8">
  <h2 class="text-3xl font-bold mb-6">Artistas</h2>

  <!-- Breadcrumb -->
  {#if stack.length > 1}
    <div class="flex items-center gap-2 text-sm text-armonia-muted mb-6 flex-wrap">
      {#each stack as crumb, i}
        {#if i < stack.length - 1}
          <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
          <span class="cursor-pointer hover:text-armonia-text transition-colors" on:click={() => goTo(i)} role="link" tabindex="0">{crumb.label}</span>
          <i class="ph ph-caret-right text-xs"></i>
        {:else}
          <span class="text-armonia-text font-medium">{crumb.label}</span>
        {/if}
      {/each}
    </div>
  {/if}

  {#if loading}
    <div class="flex items-center justify-center py-20 opacity-50">
      <i class="ph ph-circle-notch text-4xl animate-spin-slow"></i>
    </div>
  {:else if error}
    <div class="flex flex-col items-center justify-center py-20 text-red-400">
      <i class="ph ph-warning-circle text-5xl mb-4"></i><p>{error}</p>
    </div>
  {:else if top.type === 'artists'}
    {#if !artists.length}
      <div class="flex flex-col items-center justify-center py-20 opacity-50">
        <i class="ph ph-user-circle text-6xl mb-4"></i>
        <p class="text-lg">Todavía no hay artistas en tu biblioteca.</p>
      </div>
    {:else}
      <div class="relative mb-4">
        <i class="ph ph-magnifying-glass absolute left-4 top-1/2 -translate-y-1/2 text-armonia-muted"></i>
        <input type="search" bind:value={artistFilter} placeholder="Buscar en tus artistas" aria-label="Buscar en tus artistas"
          class="w-full bg-armonia-surface text-armonia-text placeholder-armonia-muted rounded-xl py-2.5 pl-11 pr-4 focus:outline-hidden focus:ring-2 focus:ring-armonia-accent/50 border border-white/10 text-sm">
      </div>
      <div class="flex items-center gap-2 mb-3 text-sm flex-wrap">
        <span class="text-armonia-muted mr-auto" role="status">{count(filteredArtists.length, 'artista', 'artistas')}</span>
        {#each [['name', 'Nombre'], ['albums', 'Más álbumes']] as [id, label]}
          <button type="button" aria-pressed={artistSort === id} on:click={() => artistSort = id}
            class="px-3 py-1.5 rounded-lg border border-white/10 {artistSort === id ? 'bg-white/10 text-armonia-text' : 'text-armonia-muted'}">{label}</button>
        {/each}
      </div>
      {#if !filteredArtists.length}
        <p class="text-center py-10 text-armonia-muted text-sm">Ningún artista coincide con «{artistFilter}».</p>
      {:else}
        <FastScroll labels={artistLabels} list={artistList} />
        <div class="flex flex-col gap-1" bind:this={artistList}>
          {#each filteredArtists as artist (artist.id)}
            <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
            <div
              class="group flex items-center gap-4 p-3 rounded-xl hover:bg-white/5 transition-all cursor-pointer"
              on:click={() => push({ type: 'artist', id: artist.id, label: artist.name })} tabindex="0" on:keydown={e=>{if(e.target===e.currentTarget && (e.key==='Enter'||e.key===' ')){e.preventDefault();push({ type: 'artist', id: artist.id, label: artist.name });}}}
              role="button"
            >
              {#if artist.coverArt && !noPicture.has(artist.id)}
                <img class="w-12 h-12 rounded-full object-cover shrink-0 bg-armonia-surface"
                     src={coverArtUrl(artist.coverArt, 96)} alt="" loading="lazy"
                     on:error={() => noPicture = new Set(noPicture).add(artist.id)}>
              {:else}
                <span class="w-12 h-12 rounded-full shrink-0 bg-armonia-surface flex items-center justify-center font-semibold text-armonia-muted" aria-hidden="true">{(artist.name || '?').trim().charAt(0).toUpperCase()}</span>
              {/if}
              <div class="flex-1 min-w-0">
                <p class="font-medium truncate">{artist.name}</p>
                <p class="text-sm text-armonia-muted">{count(artist.albumCount || 0, 'álbum', 'álbumes')}</p>
              </div>
              <i class="ph ph-caret-right text-armonia-muted opacity-0 group-hover:opacity-100 transition-opacity"></i>
            </div>
          {/each}
        </div>
      {/if}
    {/if}
  {:else if top.type === 'artist'}
    {#if !albums.length}
      <p class="text-center py-12 text-armonia-muted">Este artista no tiene álbumes propios en tu biblioteca.</p>
    {:else}
      <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
        {#each albums as album}
          <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
          <div class="group cursor-pointer" on:click={() => push({ type: 'album', id: album.id, label: album.name })} tabindex="0" on:keydown={e=>{if(e.target===e.currentTarget && (e.key==='Enter'||e.key===' ')){e.preventDefault();push({ type: 'album', id: album.id, label: album.name });}}} role="button">
            <div class="relative w-full aspect-square rounded-xl overflow-hidden mb-3 shadow-lg bg-armonia-surface">
              <img src={coverArtUrl(album.coverArt, 300)} alt="" loading="lazy"
                   class="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105">
              <div class="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                <div class="w-12 h-12 bg-armonia-accent rounded-full flex items-center justify-center shadow-xl translate-y-2 group-hover:translate-y-0 transition-transform">
                  <i class="ph-fill ph-play text-armonia-bg text-xl"></i>
                </div>
              </div>
            </div>
            <p class="font-medium truncate text-sm">{album.name}</p>
            <p class="text-xs text-armonia-muted">{count(album.songCount || 0, 'canción', 'canciones')}</p>
          </div>
        {/each}
      </div>
    {/if}
  {:else if top.type === 'album'}
    {#if !songs.length}
      <p class="text-center py-12 text-armonia-muted">Este álbum no tiene canciones.</p>
    {:else}
      <TrackList {songs} onRefresh={() => loadAlbum(top.id)} />
    {/if}
  {/if}
</div>
