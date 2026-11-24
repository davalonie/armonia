<script>
  import {mobile} from '../lib/native.js';
  import {swipeRow} from '../lib/swipeRow.js';
  import {command} from '../lib/stores/nativePlayback.js';
  import { queue, currentIndex, shuffleOn, nativeQueueOrder, trackArtUrl, removeFromQueue, reorderQueue, clearUpcoming } from '../lib/stores/playerStore.js';
  import { queuePanelOpen } from '../lib/stores/uiStore.js';

  $: current = $queue[$currentIndex] ?? null;
  $: order = mobile && $shuffleOn && $nativeQueueOrder.order?.length === $queue.length
    ? $nativeQueueOrder.order : $queue.map((_, index) => index);
  $: upcoming = order.slice(order.indexOf($currentIndex) + 1);

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
  style:transform={$queuePanelOpen ? 'none' : mobile?'translateY(105%)':'translateX(100%)'}
  inert={!$queuePanelOpen}
  role="region"
  aria-label="Cola de reproduccion"
>
  {#if mobile}<button class="queue-handle" aria-label="Cerrar hoja de cola" on:click={()=>queuePanelOpen.set(false)}><span></span></button>{/if}
  <div class="queue-head flex items-center justify-between px-5 py-4 border-b border-white/10 shrink-0">
    <h2 class="text-base font-semibold">Cola</h2>
    {#if mobile}<button class="text-sm text-armonia-accent disabled:opacity-40" disabled={!upcoming.length} on:click={clearUpcoming}>Vaciar</button>{:else}
    <button
      on:click={() => queuePanelOpen.set(false)}
      aria-label="Cerrar cola"
      class="w-9 h-9 flex items-center justify-center text-armonia-muted hover:text-white transition-colors rounded-full hover:bg-white/10"
    >
      <i class="ph ph-x text-lg"></i>
    </button>{/if}
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
              {#if mobile && !$shuffleOn}
                <button class="p-2" aria-label={`Subir ${track.title} en la cola`} disabled={i===0} on:click={()=>reorderQueue(qIdx,upcoming[i-1])}>↑</button>
                <button class="p-2" aria-label={`Bajar ${track.title} en la cola`} disabled={i===upcoming.length-1} on:click={()=>reorderQueue(qIdx,upcoming[i+1])}>↓</button>
              {/if}
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
</div>
