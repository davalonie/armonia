<script>
  // «Historial y estadisticas», as in the app (ListeningScreen): period, the summary card with its chart, your
  // number-one artist, the Top 5 and the rest of the ranking by artists, songs or albums, and what you heard lately.
  import {library, call, coverArtUrl} from '../lib/api.js';
  import {api, artUrl, toQueueTrack} from '../lib/homelab.js';
  import {currentView, openSearch} from '../lib/stores/viewStore.js';
  import {playQueue} from '../lib/stores/playerStore.js';
  import {rejectedListens} from '../lib/listenDelivery.js';
  import {listenTime, chartDate, whenHeard} from '../lib/listening.js';
  import {onMount} from 'svelte';

  const PERIODS = [['week', 'Semana'], ['month', 'Mes'], ['year', 'Año'], ['always', 'Siempre']];
  const KINDS = [['artists', 'Artistas'], ['songs', 'Canciones'], ['albums', 'Albumes']];
  let period = 'month', kind = 'artists', data = null, failed = false, version = 0;
  let directory = new Map(), delivery = {}, retrying = false, retryError = '';

  async function load() {
    const mine = ++version; data = null; failed = false;
    try {
      const r = await call(`/api/listening/summary?period=${period}`);
      if (mine === version) data = r;
    } catch { if (mine === version) failed = true; }
  }
  async function loadSide() {
    try {
      const r = await library('getArtists');
      directory = new Map((r.artists?.index || []).flatMap(i => i.artist || []).map(a => [a.name.toLowerCase(), a]));
    } catch { /* Without it the number one uses its song's cover. */ }
    try { delivery = (await api.delivery()).delivery || {}; } catch { delivery = {}; }
  }
  function choose(id) { if (id !== period) { period = id; void load(); } }
  onMount(() => currentView.subscribe(view => { if (view === 'listening') { void load(); void loadSide(); } }));

  const play = track => playQueue([{...toQueueTrack(track, artUrl(track, 300)), _from: 'Historial y estadisticas'}]);
  $: ranking = data ? data[kind] || [] : [];
  $: lead = data?.artists?.[0];
  $: leadArtist = lead ? directory.get(lead.name.toLowerCase()) : null;
  $: leadImage = lead ? (leadArtist?.coverArt ? coverArtUrl(leadArtist.coverArt, 500) : artUrl(lead.track, 500)) : '';
  $: peak = Math.max(1, ...(data?.series || []).map(p => p.seconds));
  $: pending = (delivery.pending || 0) + (delivery.sending || 0);
  async function retry() {
    retrying = true; retryError = '';
    try { await call('/api/listening/retry', {method: 'POST'}); await loadSide(); }
    catch (e) { retryError = e.message; }
    finally { retrying = false; }
  }
</script>

<section class="stats">
  <h1>Historial y estadisticas</h1>
  {#if pending || delivery.blocked}
    <p class="note" role="status">{pending ? `${pending} ${pending === 1 ? 'escucha pendiente' : 'escuchas pendientes'} de sincronizar.` : ''}
      {delivery.blocked ? `${delivery.blocked} necesitan revision.` : ''}
      {#if delivery.blocked}<button class="link" disabled={retrying} on:click={retry}>Reintentar</button>{/if}</p>
    {#if retryError}<p class="error" role="alert">{retryError}</p>{/if}
  {/if}
  {#if rejectedListens()}<p class="note" role="status">{rejectedListens()} escuchas rechazadas se conservan en este navegador. Comprueba la fecha del dispositivo.</p>{/if}

  <nav class="chips" aria-label="Periodo">{#each PERIODS as [id, label]}
    <button class="chip" class:on={period === id} aria-pressed={period === id} on:click={() => choose(id)}>{label}</button>
  {/each}</nav>

  {#if failed}<button class="link" on:click={load}>Reintentar carga de estadisticas</button>
  {:else if !data}<div class="progress" role="progressbar" aria-label="Cargando"><span></span></div>
  {:else if !data.count}<p class="muted">Todavia no hay escuchas en este periodo</p>
  {:else}
    <div class="card">
      <p class="big">{listenTime(data.seconds)}</p>
      <p class="sub">{data.count} escuchas · {data.distinct} artistas</p>
      <div class="chart" aria-hidden="true">{#each data.series as point}<span style:height="{point.seconds / peak * 100}%"></span>{/each}</div>
      <p class="range">{chartDate(data.series[0]?.date, period)} — {chartDate(data.series[data.series.length - 1]?.date, period)}</p>
    </div>

    {#if lead}
      <button class="lead" on:click={() => openSearch(lead.name)}>
        {#if leadImage}<img src={leadImage} alt="" loading="lazy" on:error={e => e.currentTarget.style.visibility = 'hidden'}>{:else}<span class="ph-img"></span>{/if}
        <b>Artista n.º 1 · {lead.name}</b>
      </button>
    {/if}

    <nav class="chips" aria-label="Ranking">{#each KINDS as [id, label]}
      <button class="chip" class:on={kind === id} aria-pressed={kind === id} on:click={() => kind = id}>{label}</button>
    {/each}</nav>

    {#each ranking as row, i}
      {#if i === 0}<h2>Top 5</h2>{/if}
      {#if i === 5}<h2>Resto del ranking</h2>{/if}
      <button class="rank" class:top={i < 5} disabled={kind === 'albums'}
        on:click={() => kind === 'songs' ? play(row.track) : openSearch(row.name)}>
        <img src={artUrl(row.track, 128)} alt="" loading="lazy" on:error={e => e.currentTarget.style.visibility = 'hidden'}>
        <span class="col"><b>{i + 1}. {row.name}</b><small>{listenTime(row.seconds)} · {row.count} escuchas</small>
          <span class="meter"><span style:width="{ranking[0].seconds ? row.seconds / ranking[0].seconds * 100 : 0}%"></span></span></span>
      </button>
    {/each}

    <h2>Escuchado recientemente</h2>
    {#each data.recent as row}
      <button class="recent" on:click={() => play(row.track)}><b>{row.track.title}</b><small>{row.track.artist} · {whenHeard(row.at)}</small></button>
    {/each}
  {/if}
</section>

<style>
  .stats{max-width:760px;margin:0 auto;padding:1.25rem 1rem 8rem;display:flex;flex-direction:column;gap:10px}
  h1{font-size:1.9rem;font-weight:800;color:#fff}
  h2{font-size:1.25rem;font-weight:700;color:#fff;margin-top:10px}
  .chips{display:flex;gap:6px;flex-wrap:wrap}
  .chip{padding:7px 14px;border-radius:8px;border:1px solid #ffffff30;font-size:.9rem;font-weight:500}
  .chip.on{background:#4a3d63;border-color:transparent;color:#fff}
  .muted{color:var(--color-armonia-muted)}
  .note{color:var(--color-armonia-muted);font-size:.88rem}
  .error{color:#ffb4a8;font-size:.88rem}
  .link{color:var(--color-armonia-accent);font-weight:600;text-align:left;padding:4px 0}
  .progress{height:4px;border-radius:2px;background:#ffffff14;overflow:hidden}
  .progress span{display:block;height:100%;width:35%;background:var(--color-armonia-accent);animation:slide 1.1s ease-in-out infinite}
  @keyframes slide{from{transform:translateX(-100%)}to{transform:translateX(300%)}}
  .card{background:#4b298c;border-radius:16px;padding:18px;color:#fff}
  .big{font-size:3.2rem;line-height:1.05;font-weight:400}
  .sub{font-size:1.45rem;margin-top:4px}
  .chart{display:flex;align-items:flex-end;height:88px;margin-top:18px;gap:2px}
  .chart span{flex:1;background:#d6baff;min-height:1px}
  .range{margin-top:6px}
  .lead{display:flex;flex-direction:column;gap:8px;text-align:left}
  .lead img,.ph-img{width:100%;height:160px;object-fit:cover;border-radius:16px;background:#ffffff10}
  .lead b{font-size:1.45rem;font-weight:500;color:#fff}
  .rank{display:flex;align-items:center;gap:14px;padding:10px 12px;border-radius:12px;text-align:left}
  .rank.top{background:#3a3149}
  .rank:not(:disabled):hover{filter:brightness(1.15)}
  .rank:disabled{cursor:default}
  .rank img{width:44px;height:44px;object-fit:cover;flex:none;background:#ffffff10}
  .col{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px}
  .col b{font-weight:500;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  small{color:var(--color-armonia-muted);font-size:.85rem}
  .meter{height:4px;margin-top:4px}
  .meter span{display:block;height:100%;border-radius:2px;background:var(--color-armonia-accent)}
  .recent{display:flex;flex-direction:column;padding:8px 12px;border-radius:10px;text-align:left}
  .recent:hover{background:#ffffff0a}
  .recent b{font-weight:500;color:#fff}
</style>
