<script>
  import {mobile} from '../lib/native.js';
  import {swipeRow} from '../lib/swipeRow.js';
  import {pullDismiss} from '../lib/pullDismiss.js';
  import {visibleQueueRows, dropPosition, stepAside} from '../lib/queueRows.js';
  import {command} from '../lib/stores/nativePlayback.js';
  import { queue, currentIndex, shuffleOn, nativeQueueOrder, trackArtUrl, removeFromQueue, reorderQueue, clearUpcoming, playing } from '../lib/stores/playerStore.js';
  import { queuePanelOpen } from '../lib/stores/uiStore.js';
  import MaterialIcon from './MaterialIcon.svelte';
  import {artSize} from '../lib/api.js';
  import NowPlayingMark from './NowPlayingMark.svelte';

  $: current = $queue[$currentIndex] ?? null;
  $: order = mobile && $shuffleOn && $nativeQueueOrder.order?.length === $queue.length
    ? $nativeQueueOrder.order : $queue.map((_, index) => index);
  $: upcoming = order.slice(order.indexOf($currentIndex) + 1);

  // Phone: the app's QueueSheet. One list from the current song on, in play order; a row is moved by
  // its handle (the reorderable list: it follows the finger and the others step aside; with shuffle on,
  // unlike the app and as the user asked, it moves in the order they will play in), removed by a swipe
  // to either side, and the sheet closes when pulled down.
  $: rows = mobile ? visibleQueueRows($queue.map(t => t?.id), order, $currentIndex) : [];
  $: currentPos = rows.findIndex(r => r.index === $currentIndex);
  $: automatic = new Set($nativeQueueOrder.automatic || []);
  $: picked = new Set($nativeQueueOrder.handPicked || []);
  let pullY = 0;
  $: if (!$queuePanelOpen) { pullY = 0; drag = null; }
  const closeByPull = () => { pullY = 0; queuePanelOpen.set(false); };

  let listEl, drag = null, settling = false, scrolling = 0;
  function grab(e, position) {
    if (!e.isPrimary) return;
    e.preventDefault(); e.stopPropagation();
    e.currentTarget.setPointerCapture?.(e.pointerId);
    const height = e.currentTarget.closest('.q-row').offsetHeight;
    drag = {from: position, to: position, id: e.pointerId, y: e.clientY, last: e.clientY, scroll: listEl.scrollTop, height, dy: 0};
    cancelAnimationFrame(scrolling);
    scrolling = requestAnimationFrame(edgeScroll);
  }
  function follow() {
    const dy = drag.last - drag.y + listEl.scrollTop - drag.scroll;
    drag = {...drag, dy, to: dropPosition(drag.from, dy, drag.height, rows.length)};
  }
  function moveGrab(e) { if (drag && !drag.dropped && e.pointerId === drag.id) { drag.last = e.clientY; follow(); } }
  // Near the top or bottom edge the list scrolls under the finger, as the reorderable list does.
  function edgeScroll() {
    if (!drag || drag.dropped) return;
    const box = listEl.getBoundingClientRect(), edge = 48;
    const speed = drag.last < box.top + edge ? -(box.top + edge - drag.last) / 4
      : drag.last > box.bottom - edge ? (drag.last - box.bottom + edge) / 4 : 0;
    if (speed) { listEl.scrollTop += Math.max(-12, Math.min(12, speed)); follow(); }
    scrolling = requestAnimationFrame(edgeScroll);
  }
  function dropGrab(e, cancelled = false) {
    if (!drag || drag.dropped || e.pointerId !== drag.id) return;
    cancelAnimationFrame(scrolling);
    const {from, to} = drag;
    if (cancelled || from === to || !rows[from] || !rows[to]) { drag = null; return; }
    // The row settles in its new place and stays there until the native queue answers.
    drag = {...drag, dy: (to - from) * drag.height, dropped: true};
    reorderQueue(rows[from].index, rows[to].index);
    setTimeout(() => { if (drag?.dropped) drag = null; }, 1500);
  }
  // The moved queue arrives: the rows take their new order without animating back.
  $: queueArrived($queue);
  function queueArrived() {
    if (!drag) return;
    if (drag.dropped) { settling = true; drag = null; requestAnimationFrame(() => requestAnimationFrame(() => settling = false)); }
  }
  // The song changed under the finger: the positions no longer mean the same rows.
  $: songChanged($currentIndex);
  function songChanged() { if (drag && !drag.dropped) { cancelAnimationFrame(scrolling); drag = null; } }
  const shiftOf = (position, d) => !d ? 0 : position === d.from ? d.dy : stepAside(position, d.from, d.to, d.height);

  let dragSrcIdx = null;
  let dragOverIdx = null;

  function onDragStart(e, qIdx) {
    dragSrcIdx = qIdx;
    e.dataTransfer.effectAllowed = 'move';
    requestAnimationFrame(() => { if (e.target) e.target.style.opacity = '0.4'; });
  }

  function onDragEnd(e) {
    dragSrcIdx = null;
    dragOverIdx = null;
    if (e.target) e.target.style.opacity = '';
  }

  function onDragOver(e, qIdx) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    dragOverIdx = qIdx;
  }

  function onDrop(e, qIdx) {
    e.preventDefault();
    dragOverIdx = null;
    if (dragSrcIdx === null || dragSrcIdx === qIdx) return;
    reorderQueue(dragSrcIdx, qIdx);
    dragSrcIdx = null;
  }
</script>

<svelte:window on:keydown={e=>{if(e.key==='Escape'&&$queuePanelOpen){e.stopPropagation();queuePanelOpen.set(false);}}}/>

<!-- Backdrop -->
{#if $queuePanelOpen}
  <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
  <div class="fixed inset-0 z-155 bg-black/40" on:click={() => queuePanelOpen.set(false)}></div>
{/if}

<!-- Panel -->
<div
  class="queue-panel fixed inset-y-0 right-0 w-full sm:w-96 z-160 flex flex-col bg-armonia-surface border-l border-white/10 shadow-2xl transition-transform duration-300 ease-in-out"
  style:transform={$queuePanelOpen ? (pullY ? `translateY(${pullY}px)` : 'none') : mobile?'translateY(105%)':'translateX(100%)'}
  style:transition={mobile ? (pullY ? 'none' : 'transform 300ms cubic-bezier(.4,0,.2,1)') : null}
  inert={!$queuePanelOpen}
  role="region"
  aria-label="Cola de reproduccion"
>
  {#if mobile}
    <div class="q-top" use:pullDismiss={{enabled: $queuePanelOpen, onPull: y => pullY = y, onDismiss: closeByPull}}>
      <button class="queue-handle" aria-label="Cerrar hoja de cola" on:click={()=>queuePanelOpen.set(false)}><span></span></button>
      <div class="q-head">
        <h2>Cola</h2>
        <button class="q-clear" disabled={!(currentPos >= 0 && currentPos < rows.length - 1)} on:click={clearUpcoming}>Vaciar</button>
      </div>
      <p class="q-note">{$shuffleOn?'Aleatorio activado: se muestra el orden real. Arrastra para reordenar':'Arrastra para reordenar'}</p>
      <hr>
    </div>
    {#if !$queue.length}
      <p class="q-empty">La cola esta vacia</p>
    {:else}
      <div class="q-list" bind:this={listEl} role="list">
        {#each rows as row, position (row.key)}
          {@const track = $queue[row.index]}
          {@const isCurrent = row.index === $currentIndex}
          {@const auto = !!track._auto || automatic.has(track.id)}
          <!-- svelte-ignore a11y-click-events-have-key-events a11y-interactive-supports-focus -->
          <div class="q-row" class:current={isCurrent} class:lifted={drag && !drag.dropped && drag.from === position}
            role="listitem" aria-label={track.title}
            style:transform={shiftOf(position, drag) ? `translateY(${shiftOf(position, drag)}px)` : null}
            style:transition={settling || (drag && !drag.dropped && drag.from === position) ? 'none' : null}
            use:swipeRow={{enabled: !drag, both: true, commit: () => removeFromQueue(row.index)}}
            on:click={() => command('jump', {index: row.index})}>
              <span class="q-grip" data-drag-handle role="button" tabindex="-1" aria-label="Arrastra para reordenar"
                on:pointerdown={e => grab(e, position)} on:pointermove={moveGrab}
                on:pointerup={dropGrab} on:pointercancel={e => dropGrab(e, true)} on:click|stopPropagation>
                <MaterialIcon name="drag_handle" size={28} />
              </span>
            <span class="q-art">
              <img src={trackArtUrl(track, artSize(44, 128))} alt="" on:error={e=>e.currentTarget.style.opacity=0}>
              {#if isCurrent}<NowPlayingMark playing={$playing} veil={.55} />{/if}
            </span>
            <span class="q-text">
              <b>{track.title ?? '—'}</b>
              <small>{#if picked.has(row.index) && position > currentPos && !auto}<span class="q-mine" role="img" aria-label="Añadida por ti"><MaterialIcon name="queue_music" size={15} /></span>{/if}<span class="q-artist">{auto ? `Musica similar · ${track.artist ?? '—'}` : track.artist ?? '—'}</span></small>
            </span>
          </div>
        {/each}
      </div>
    {/if}
  {:else}
  <div class="queue-head flex items-center justify-between px-5 py-4 border-b border-white/10 shrink-0">
    <h2 class="text-base font-semibold">Cola</h2>
    <button
      on:click={() => queuePanelOpen.set(false)}
      aria-label="Cerrar cola"
      class="w-9 h-9 flex items-center justify-center text-armonia-muted hover:text-white transition-colors rounded-full hover:bg-white/10"
    >
      <i class="ph ph-x text-lg"></i>
    </button>
  </div>

  <div class="flex-1 overflow-y-auto pb-6">
    {#if current}
      <div class="queue-current px-4 pt-5 pb-3">
        <p class="text-[10px] font-semibold text-armonia-muted uppercase tracking-widest mb-3">{current._auto?'Sonando · continuacion automatica':'Sonando'}</p>
        <div class="flex items-center gap-3 p-2 rounded-xl bg-white/5">
          <img on:load={e=>e.currentTarget.style.opacity=1} on:error={e=>{if(mobile)e.currentTarget.style.opacity=0;}} src={trackArtUrl(current, 64)} alt="" class="w-10 h-10 rounded-md object-cover shrink-0 bg-armonia-bg">
          <div class="flex-1 min-w-0">
            <p class="text-sm font-medium truncate text-armonia-accent">{current.title ?? '—'}</p>
            <p class="text-xs text-armonia-muted truncate">{current.artist ?? '—'}</p>
          </div>
        </div>
      </div>
    {/if}

    {#if upcoming.length}
      <div class="px-4 pb-4">
        <div class="queue-upcoming flex items-center justify-between mb-3">
          <p class="text-[10px] font-semibold text-armonia-muted uppercase tracking-widest">A continuacion</p>
          <button on:click={clearUpcoming} class="text-xs text-armonia-muted hover:text-red-400 transition-colors">Vaciar</button>
        </div>
        <div class="flex flex-col gap-0.5">
          {#each upcoming as qIdx, i}
            {@const track = $queue[qIdx]}
            <!-- svelte-ignore a11y-click-events-have-key-events -->
            <div
              class="flex items-center gap-2 p-2 rounded-xl hover:bg-white/5 group cursor-pointer transition-colors {dragOverIdx === qIdx && dragSrcIdx !== qIdx ? 'border-t-2 border-armonia-accent' : ''}"
              use:swipeRow={{enabled:mobile,both:true,commit:()=>removeFromQueue(qIdx)}} style:touch-action={mobile?'pan-y':null}
              draggable={!mobile}
              on:dragstart={e => onDragStart(e, qIdx)}
              on:dragend={onDragEnd}
              on:dragover={e => onDragOver(e, qIdx)}
              on:dragleave={() => { dragOverIdx = null; }}
              on:drop={e => onDrop(e, qIdx)}
              role="listitem"
            >
              <i class="ph ph-dots-six-vertical text-armonia-muted text-lg shrink-0 cursor-grab opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"></i>
              <img on:load={e=>e.currentTarget.style.opacity=1} on:error={e=>{if(mobile)e.currentTarget.style.opacity=0;}} src={trackArtUrl(track, 64)} alt="" class="w-10 h-10 rounded-md object-cover shrink-0 bg-armonia-bg pointer-events-none">
              <div class="flex-1 min-w-0" class:pointer-events-none={!mobile}>
                {#if mobile}<button data-swipe-handle class="block text-left text-sm font-medium truncate w-full" aria-label={`Reproducir ${track.title}`} on:click={()=>command('jump',{index:qIdx})}>{track.title}</button>{:else}<p class="text-sm font-medium truncate">{track.title ?? '—'}</p>{/if}
                <p class="text-xs text-armonia-muted truncate">{#if mobile && $nativeQueueOrder.handPicked?.includes(qIdx)}Añadida por ti · {/if}{#if track._auto || $nativeQueueOrder.automatic?.includes(track.id)}<i aria-hidden="true" class="ph ph-infinity text-armonia-accent"></i> Musica similar · {/if}{track.artist ?? '—'}</p>
              </div>
              <button
                aria-label={`Quitar ${track.title} de la cola`}
                class="w-8 h-8 flex items-center justify-center text-armonia-muted hover:text-white rounded-full hover:bg-white/10 transition-all sm:opacity-0 sm:group-hover:opacity-100 shrink-0"
                on:click|stopPropagation={() => removeFromQueue(qIdx)}
              >
                <i class="ph ph-x text-sm pointer-events-none"></i>
              </button>
            </div>
          {/each}
        </div>
      </div>
    {:else if !current}
      <div class="flex flex-col items-center justify-center h-full gap-3 opacity-40 p-8 text-center">
        <i class="ph ph-list text-5xl"></i>
        <p class="text-sm">La cola esta vacia</p>
      </div>
    {/if}
  </div>
  {/if}
</div>

<style>
  /* The phone's QueueSheet rows (ui/player/QueueSheet.kt): 60 dp, handle, 44 dp cover, tint on the current one. */
  .q-top{flex:none;touch-action:none}
  .q-head{display:flex;align-items:center;justify-content:space-between;padding:8px 16px}
  .q-head h2{font-size:22px;line-height:28px;font-weight:600}
  .q-clear{height:40px;padding:0 12px;border-radius:20px;color:var(--color-armonia-accent);font-size:14px;font-weight:500}
  .q-clear:disabled{color:#eeeeee61}
  .q-note{padding:4px 16px;font-size:12px;line-height:16px;color:#eeeeee99}
  .q-top hr{border:0;border-top:1px solid #222;margin:0}
  .q-empty{padding:32px;text-align:center;color:#eeeeee99}
  .q-list{flex:0 1 auto;min-height:0;max-height:560px;overflow-y:auto;overflow-x:hidden;padding:8px 0;overscroll-behavior:contain}
  .q-row{position:relative;display:flex;align-items:center;height:60px;padding-right:16px;background:var(--color-armonia-surface);
    touch-action:pan-y;transition:transform 250ms cubic-bezier(.2,.8,.2,1)}
  .q-row.current{background:linear-gradient(#4b2e0059,#4b2e0059),var(--color-armonia-surface)}
  .q-row.lifted{z-index:2}
  /* As the app's handle: the 28 dp icon and its padding (8 dp before, 4 after) are all the grip. */
  .q-grip{flex:none;display:grid;place-items:center;box-sizing:content-box;width:28px;height:28px;padding:0 4px 0 8px;color:#eeeeee73;touch-action:none}
  .q-art{position:relative;flex:none;width:44px;height:44px;border-radius:4px;overflow:hidden;background:#1e1e1e}
  .q-art img{width:100%;height:100%;object-fit:cover}
  .q-text{flex:1;min-width:0;margin-left:12px;display:flex;flex-direction:column}
  .q-text b{font-size:14px;line-height:20px;font-weight:400;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#eee}
  .current .q-text b{font-weight:600;color:var(--color-armonia-accent)}
  .q-text small{display:flex;align-items:center;gap:4px;font-size:12px;line-height:16px;color:#eeeeee99;min-width:0}
  .q-artist{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .q-mine{flex:none;color:var(--color-armonia-accent)}
</style>
