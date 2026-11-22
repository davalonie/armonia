<script>
  // «Guardar en una playlist», as in the app: search, «Nueva playlist», order, Tus favoritos and your playlists with
  // a tick where the song already is; Guardar applies only what changed. A bottom sheet on a phone, a dialog wider.
  import {saveSheet, loadSheet, saveChanges, createPlaylist, FAVORITES} from '../lib/saveSong.js';
  import {coverArtUrl} from '../lib/api.js';
  import Cover from './Cover.svelte';
  let track = null, playlists = [], included = new Set(), selected = new Set(), needsDownload = false;
  let loading = false, busy = false, ready = false, message = '', query = '', byCount = false, creating = false, name = '';
  let opened = 0;

  $: if ($saveSheet !== track) open($saveSheet);
  async function open(next) {
    track = next; const mine = ++opened;
    playlists = []; included = new Set(); selected = new Set(); ready = false; message = ''; query = ''; creating = false; name = '';
    if (!next) return;
    loading = true;
    try {
      const sheet = await loadSheet(next);
      if (mine !== opened) return;
      ({playlists, included, needsDownload} = sheet);
      selected = new Set(included); ready = true;
    } catch (e) { if (mine === opened) message = e.message || 'No se pudieron comprobar las playlists'; }
    finally { if (mine === opened) loading = false; }
  }
  const close = () => { if (!busy) saveSheet.set(null); };
  function toggle(id) { if (!ready || busy) return; const s = new Set(selected); s.has(id) ? s.delete(id) : s.add(id); selected = s; }
  const fold = s => (s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  $: shown = playlists.filter(p => !query.trim() || fold(p.name).includes(fold(query.trim())))
    .sort((a, b) => byCount ? (b.songCount || 0) - (a.songCount || 0) : a.name.localeCompare(b.name, 'es'));
  $: changed = selected.size !== included.size || [...selected].some(x => !included.has(x));

  async function create() {
    const n = name.trim(); if (!n || busy) return;
    busy = true; message = '';
    try {
      const before = new Set(playlists.map(p => p.id));
      await createPlaylist(n);
      const sheet = await loadSheet(track);
      playlists = sheet.playlists;
      const made = playlists.filter(p => !before.has(p.id) && p.name === n);
      if (made.length === 1) selected = new Set([...selected, made[0].id]);
      message = 'Playlist creada y marcada. Pulsa Guardar para añadir la canción.';
      name = ''; creating = false;
    } catch (e) { message = e.message; }
    finally { busy = false; }
  }
  async function confirm() {
    if (busy || !ready) return;
    busy = true; message = '';
    try {
      const r = await saveChanges(track, included, selected, note => { message = note; if (!note) needsDownload = false; });
      included = r.included;
      if (r.failures.length) message = r.failures.join(' · '); else { busy = false; saveSheet.set(null); }
    } catch (e) { message = e.message; }
    finally { busy = false; }
  }
</script>

<svelte:window on:keydown={e => { if (track && e.key === 'Escape') close(); }} />

{#if track}
  <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
  <div class="scrim" on:click={close}></div>
  <section class="sheet" role="dialog" aria-modal="true" aria-labelledby="save-title">
    <span class="grip" aria-hidden="true"></span>
    <h2 id="save-title">Guardar en una playlist</h2>
    <p class="song">{track.title} · {track.artist}</p>
    <label class="search"><i aria-hidden="true" class="ph ph-magnifying-glass"></i>
      <input type="search" bind:value={query} placeholder="Buscar playlist" aria-label="Buscar playlist"></label>
    <div class="row-tools">
      <button class="text" disabled={busy} on:click={() => creating = !creating}><i aria-hidden="true" class="ph ph-plus"></i> Nueva playlist</button>
      <button class="text" on:click={() => byCount = !byCount}>{byCount ? 'Orden: más canciones' : 'Orden: nombre'}</button>
    </div>
    {#if creating}
      <form class="create" on:submit|preventDefault={create}>
        <input bind:value={name} maxlength="150" placeholder="Nombre de la playlist nueva" aria-label="Nombre de la playlist nueva">
        <button class="filled" disabled={busy || loading || !name.trim()}>Crear</button>
      </form>
    {/if}
    {#if loading || busy}<div class="progress" role="progressbar" aria-label="Cargando"><span></span></div>{/if}
    {#if message}<p class="message" role="status">{message}</p>{/if}

    <ul class="lists">
      <li><button class="item" role="checkbox" aria-checked={selected.has(FAVORITES)} disabled={!ready || busy} on:click={() => toggle(FAVORITES)}>
        <span class="art"><Cover variant="liked" /></span>
        <span class="text-col"><b>Tus favoritos</b>{#if included.has(FAVORITES)}<small class="in">Ya está en tus favoritos</small>{/if}</span>
        <span class="box" class:on={selected.has(FAVORITES)} aria-hidden="true"><i class="ph-bold ph-check"></i></span></button></li>
      {#if !shown.length && !loading}
        <li class="none">{playlists.length ? `Ninguna playlist coincide con «${query.trim()}».` : 'Todavía no tienes playlists. Crea una con «Nueva playlist».'}</li>
      {/if}
      {#each shown as p (p.id)}
        <li><button class="item" role="checkbox" aria-checked={selected.has(p.id)} disabled={!ready || busy} on:click={() => toggle(p.id)}>
          <span class="art"><Cover covers={p.coverArt ? [coverArtUrl(p.coverArt, 96)] : []} size={96} /></span>
          <span class="text-col"><b>{p.name}</b>
            <small class:in={included.has(p.id)}>{included.has(p.id) ? 'Ya está en esta playlist' : p.songCount === 1 ? '1 canción' : `${p.songCount || 0} canciones`}</small></span>
          <span class="box" class:on={selected.has(p.id)} aria-hidden="true"><i class="ph-bold ph-check"></i></span></button></li>
      {/each}
    </ul>

    <div class="actions">
      <button class="text" disabled={busy} on:click={close}>Cancelar</button>
      <button class="filled" disabled={busy || !ready || !changed} on:click={confirm}>{needsDownload ? 'Descargar y guardar' : 'Guardar'}</button>
    </div>
  </section>
{/if}

<style>
  .scrim{position:fixed;inset:0;background:#000a;z-index:190}
  .sheet{position:fixed;z-index:200;left:0;right:0;bottom:0;max-height:min(640px,88vh);display:flex;flex-direction:column;
    background:#1f1b26;border-radius:22px 22px 0 0;padding:8px 16px calc(12px + env(safe-area-inset-bottom,0px));box-shadow:0 -10px 40px #0009}
  @media(min-width:768px){.sheet{left:50%;right:auto;bottom:auto;top:50%;transform:translate(-50%,-50%);width:min(520px,92vw);border-radius:22px;padding:20px}}
  .grip{align-self:center;width:36px;height:4px;border-radius:2px;background:#ffffff40;margin-bottom:10px}
  @media(min-width:768px){.grip{display:none}}
  h2{font-size:1.35rem;font-weight:700;color:#fff}
  .song{color:var(--color-armonia-muted);font-size:.85rem;margin:2px 0 10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .search{display:flex;align-items:center;gap:8px;height:48px;padding:0 16px;border-radius:28px;background:#ffffff14;color:var(--color-armonia-muted)}
  .search input{flex:1;min-width:0;background:transparent;border:0;outline:0;color:#fff}
  .row-tools{display:flex;justify-content:space-between;margin-top:4px}
  .text{display:flex;align-items:center;gap:6px;padding:10px 12px;border-radius:20px;color:var(--color-armonia-accent);font-weight:600;font-size:.9rem}
  .text:hover{background:#ffffff0d}
  .text:disabled{opacity:.5}
  .create{display:flex;gap:8px;margin-bottom:6px}
  .create input{flex:1;min-width:0;background:#ffffff12;border:1px solid #ffffff26;border-radius:8px;padding:10px 12px;color:#fff}
  .filled{padding:10px 20px;border-radius:20px;background:var(--color-armonia-accent);color:#16121d;font-weight:700}
  .filled:disabled{opacity:.45}
  .progress{height:4px;border-radius:2px;background:#ffffff14;overflow:hidden;margin:4px 0}
  .progress span{display:block;height:100%;width:35%;background:var(--color-armonia-accent);animation:slide 1.1s ease-in-out infinite}
  @keyframes slide{from{transform:translateX(-100%)}to{transform:translateX(300%)}}
  .message{color:var(--color-armonia-accent);font-size:.85rem;margin:4px 0}
  .lists{list-style:none;margin:0;padding:0;overflow-y:auto;flex:0 1 auto;min-height:0}
  .item{width:100%;display:flex;align-items:center;gap:12px;padding:6px 4px;border-radius:8px;text-align:left}
  .item:hover:not(:disabled){background:#ffffff0a}
  .item:disabled{cursor:default}
  .art{width:48px;height:48px;flex:none;border-radius:6px;overflow:hidden;display:block}
  .text-col{flex:1;min-width:0;display:flex;flex-direction:column}
  .text-col b{font-weight:600;color:#fff;font-size:.95rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .text-col small{color:var(--color-armonia-muted);font-size:.8rem}
  .text-col small.in{color:var(--color-armonia-accent)}
  .box{flex:none;width:22px;height:22px;border-radius:4px;border:2px solid #ffffff80;display:grid;place-items:center;color:transparent;font-size:.8rem}
  .box.on{background:var(--color-armonia-accent);border-color:var(--color-armonia-accent);color:#16121d}
  .item:disabled .box{opacity:.5}
  .none{color:var(--color-armonia-muted);padding:16px 4px;font-size:.9rem}
  .actions{display:flex;justify-content:flex-end;gap:8px;padding-top:8px}
</style>
