<script>
  import MaterialIcon from './MaterialIcon.svelte';
  import {mobile} from '../lib/native.js';
  import PhoneDownloads from '../components/PhoneDownloads.svelte';
  import ShuffleToggle from './ShuffleToggle.svelte';
  // Read-and-play view of an ordered list of songs: generated lists, library
  // playlists, favourites and albums opened from Inicio. Playback always goes
  // through the shared queue; this component owns no audio.
  import {createEventDispatcher} from 'svelte';
  import Cover from './Cover.svelte';
  import {currentTrack,playing,playQueue,playList,playNext,undoPlayNext,addToQueue,togglePlayPause,isPreview,prepareTrack} from '../lib/stores/playerStore.js';
  import {library as libApi} from '../lib/api.js';
  import {fromQueueTrack} from '../lib/homelab.js';
  import {songMenu} from '../lib/trackActions.js';
  import {showContextMenu} from '../lib/stores/contextMenuStore.js';
  import {showPlaylistPicker} from '../lib/stores/playlistPickerStore.js';
  import {showToast} from '../lib/stores/toastStore.js';
  import {swipeRow} from '../lib/swipeRow.js';
  import {queuedNotice} from '../lib/queueNotice.js';

  export let title='';
  export let eyebrow='';
  export let description='';
  export let meta='';
  export let covers=[];
  export let variant='plain';
  export let label='';
  export let rows=[];          // [{queue, art}]
  export let context=null;     // {kind,id}: reported as recently played once audio starts
  export let loading=false;
  export let notice='';
  export let busy=false;
  export let onSave=null;
  export let onRefresh=null;
  const dispatch=createEventDispatcher();

  $: tracks=rows.map(r=>({...r.queue,...(context?{_playlist:context}:{}),_from:title}));
  $: activeHere=rows.some(r=>r.queue.id===$currentTrack?.id);
  // Opening a list makes its first song the likely next press: resolve only that one ahead.
  $: if(rows.length&&!activeHere)prepareTrack(rows[0].queue);
  function playAll(){if(activeHere){togglePlayPause();return;}playList(tracks);}
  function menu(e,row){e.stopPropagation();void songMenu(e.currentTarget,row.queue);}
  // On the phone a row slides right to queue the song, as in every list of the app.
  const queueRow=row=>void queuedNotice(addToQueue(row.queue),row.queue);
</script>

<article class="detail">
  <header class="hero {variant}">
    <button class="back" aria-label="Volver" on:click={()=>dispatch('back')}><i aria-hidden="true" class="ph ph-arrow-left"></i></button>
    <div class="hero-body">
      <div class="hero-cover"><Cover {covers} {variant} {label} size={400} /></div>
      <div class="hero-text">
        {#if eyebrow}<p class="eyebrow">{eyebrow}</p>{/if}
        <h1>{title}</h1>
        {#if description}<p class="description">{description}</p>{/if}
        {#if meta}<p class="meta">{meta}</p>{/if}
      </div>
    </div>
  </header>

    {#if mobile}{#if context?.kind === "local"}<PhoneDownloads id={context.id} {title} {tracks} />{/if}{/if}
  <div class="controls">
    {#if onSave}<button class="ghost" disabled={busy||!rows.length} on:click={onSave} aria-label="Guardar una copia en tu biblioteca" title="Guardar una copia en tu biblioteca"><i aria-hidden="true" class="ph ph-plus-circle"></i></button>{/if}
    {#if onRefresh}<button class="ghost" class:spinning={busy} disabled={busy} on:click={onRefresh} aria-label="Actualizar esta lista" title="Actualizar esta lista"><i aria-hidden="true" class="ph ph-arrows-clockwise"></i></button>{/if}
    <span class="spacer"></span>
    <ShuffleToggle />
    <button class="play" disabled={!rows.length} on:click={playAll} aria-label={activeHere&&$playing?`Pausar ${title}`:`Reproducir ${title}`}><i aria-hidden="true" class="ph-fill {activeHere&&$playing?'ph-pause':'ph-play'}"></i></button>
  </div>

  {#if notice}<p class="notice" role="status">{notice}</p>{/if}
  {#if loading}
    <div class="rows" aria-busy="true">{#each Array(6) as _}<div class="row skeleton"><span class="art"></span><span class="lines"><i></i><i></i></span></div>{/each}</div>
  {:else if !rows.length}
    <div class="empty"><slot name="empty"><p>Esta lista no tiene canciones todavia.</p></slot></div>
  {:else}
    <ol class="rows">
      {#each rows as row,i (i)}
        {@const active=row.queue.id===$currentTrack?.id}
        <li class="row" class:active use:swipeRow={{enabled:!!mobile,commit:()=>queueRow(row)}} style:touch-action={mobile?'pan-y':null}>
          <button class="main" data-swipe-handle on:click={()=>playQueue(tracks,i)} aria-label={`Reproducir ${row.queue.title}, de ${row.queue.artist}`}>
            <span class="art">
              <i aria-hidden="true" class="ph ph-music-note"></i>
              {#if row.art}<img src={row.art} alt="" loading="lazy" referrerpolicy="no-referrer" on:error={e=>e.currentTarget.style.visibility='hidden'}>{/if}
              {#if active}<span class="bars" class:paused={!$playing} aria-hidden="true"><b></b><b></b><b></b></span>{/if}
            </span>
            <span class="lines"><strong>{row.queue.title}</strong><small>{row.queue.artist}</small></span>
          </button>
          <button class="dots" aria-label={`Opciones de ${row.queue.title}`} on:click={e=>menu(e,row)}><MaterialIcon name="more_vert" /></button>
        </li>
      {/each}
    </ol>
  {/if}
</article>

<style>
  .detail{padding-bottom:2rem}
  .hero{padding:1rem 1rem 1.25rem;background:linear-gradient(180deg,#5a37a8 0%,#2c1f4d 62%,var(--color-armonia-bg) 100%)}
  .hero.weekly{background:linear-gradient(180deg,#6d3fd0 0%,#2b1c50 62%,var(--color-armonia-bg) 100%)}
  .hero.plain{background:linear-gradient(180deg,#3c3550 0%,#201b2a 62%,var(--color-armonia-bg) 100%)}
  .back{width:40px;height:40px;border-radius:50%;background:#0000004d;display:grid;place-items:center;font-size:1.3rem;color:#fff}
  .back:hover{background:#00000080}
  .hero-body{display:flex;flex-direction:column;align-items:center;gap:1rem;margin-top:.5rem}
  .hero-cover{width:min(52vw,220px)}
  .hero.liked .hero-cover{display:none}
  .hero-text{width:100%;min-width:0}
  .eyebrow{font-size:.75rem;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:#ffffffc0;margin-bottom:.25rem}
  h1{font-size:clamp(1.6rem,6vw,3.4rem);font-weight:800;letter-spacing:-.02em;line-height:1.1;overflow-wrap:anywhere}
  .description{color:#ffffffb8;font-size:.9rem;margin-top:.5rem;max-width:60ch}
  .meta{color:#ffffff99;font-size:.82rem;margin-top:.35rem}
  .controls{display:flex;align-items:center;gap:.5rem;padding:0 1rem .75rem}
  .spacer{flex:1}
  .ghost{width:44px;height:44px;border-radius:50%;display:grid;place-items:center;font-size:1.55rem;color:#ffffffb0}
  .ghost:hover:not(:disabled){color:#fff;background:#ffffff12}
  .ghost:disabled,.play:disabled{opacity:.35;cursor:default}
  .spinning i{animation:spin 1.2s linear infinite}
  .play{width:56px;height:56px;border-radius:50%;background:var(--color-armonia-accent);color:#1a1126;display:grid;place-items:center;font-size:1.6rem;box-shadow:0 8px 20px #0006;transition:transform .12s}
  .play:hover:not(:disabled){transform:scale(1.05);background:var(--color-armonia-accentHover)}
  .notice{margin:0 1rem .75rem;font-size:.85rem;color:#d9c9ff;background:#c4a3ff14;border-radius:8px;padding:.6rem .8rem}
  .empty{padding:2rem 1rem;color:#b3b3b3;text-align:center}
  .rows{list-style:none;margin:0;padding:0 .5rem}
  .row{display:flex;align-items:center;border-radius:6px}
  .row:hover{background:#ffffff0f}
  .main{flex:1;min-width:0;display:flex;align-items:center;gap:.75rem;padding:.4rem .5rem;text-align:left}
  .art{position:relative;flex:none;width:48px;height:48px;border-radius:4px;overflow:hidden;background:#2a2433;display:grid;place-items:center;color:#ffffff40;font-size:1.3rem}
  .art img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
  .lines{min-width:0;display:flex;flex-direction:column;gap:.1rem}
  .lines strong{font-weight:500;font-size:1rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .lines small{color:#b3b3b3;font-size:.85rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .row.active strong{color:var(--color-armonia-accent)}
  .dots{flex:none;width:44px;height:44px;display:grid;place-items:center;font-size:1.4rem;color:#b3b3b3;border-radius:50%}
  .dots:hover{color:#fff}
  .bars{position:absolute;inset:0;background:#000000a6;display:flex;align-items:flex-end;justify-content:center;gap:3px;padding-bottom:15px}
  .bars b{width:3px;height:14px;background:var(--color-armonia-accent);transform-origin:bottom;animation:musicBar 1s ease-in-out infinite}
  .bars b:nth-child(2){animation-delay:.2s}.bars b:nth-child(3){animation-delay:.4s}
  .bars.paused b{animation-play-state:paused}
  .skeleton{padding:.4rem .5rem;gap:.75rem}
  .skeleton .lines i{display:block;height:.7rem;border-radius:4px;background:#ffffff14;width:11rem}
  .skeleton .lines i+i{width:7rem;margin-top:.45rem}
  @keyframes spin{to{transform:rotate(360deg)}}
  @media(min-width:768px){
    .hero{padding:1.5rem 2rem 1.75rem}
    .hero-body{flex-direction:row;align-items:flex-end;gap:1.75rem;margin-top:1rem}
    .hero-cover{width:clamp(160px,17vw,232px);flex:none}
    .controls{padding:0 2rem 1rem;flex-direction:row-reverse;justify-content:flex-end}
    .spacer{display:none}
    .rows{padding:0 1.5rem}
    .notice{margin:0 2rem 1rem}
    .main{padding:.3rem .5rem}
    .art{width:40px;height:40px}
    .lines strong{font-size:.95rem}
    .dots{opacity:0}.row:hover .dots,.dots:focus-visible{opacity:1}
  }
</style>
