<script>
  import { contextMenuState,closeContextMenu } from '../lib/stores/contextMenuStore.js';
  import {tick} from 'svelte';
  let menu;
  $: if($contextMenuState.visible)tick().then(()=>menu?.querySelector('button')?.focus());
  function keys(e){
    if(e.key==='Escape')closeContextMenu();
    if(['ArrowDown','ArrowUp'].includes(e.key)){
      e.preventDefault();
      const buttons=[...menu.querySelectorAll('button[role=menuitem],button.star:first-of-type')],i=buttons.indexOf(document.activeElement);
      buttons[(i+(e.key==='ArrowDown'?1:buttons.length-1))%buttons.length]?.focus();
    }
  }
  // A rating stays in the menu: the stars change in place so the choice is visible before closing.
  async function rate(item,value){
    const next=item.value===value?0:value,before=item.value;
    item.value=next;contextMenuState.update(s=>s);
    try{await item.onRate(next);}catch{item.value=before;contextMenuState.update(s=>s);}
  }
</script>

{#if $contextMenuState.visible}
  <button class="scrim" aria-label="Cerrar menú" tabindex="-1" on:click={closeContextMenu}></button>
  <!-- svelte-ignore a11y-click-events-have-key-events -->
  <div
    bind:this={menu} role="menu" aria-label={$contextMenuState.header?`Acciones de ${$contextMenuState.header.title}`:'Acciones'} tabindex="-1"
    on:keydown={keys} on:click|stopPropagation
    class="song-menu fixed z-200 bg-armonia-surface border border-white/10 rounded-xl shadow-2xl py-1 min-w-[240px]"
    style:top="{$contextMenuState.y}px"
    style:left="{$contextMenuState.x}px"
  >
    {#if $contextMenuState.header}
      {@const h=$contextMenuState.header}
      <div class="grip" aria-hidden="true"></div>
      <div class="head">
        <span class="art">{#if h.art}<img src={h.art} alt="" referrerpolicy="no-referrer" on:error={e=>e.currentTarget.style.visibility='hidden'}>{:else}<i aria-hidden="true" class="ph ph-music-note"></i>{/if}</span>
        <span class="who"><b>{h.title}</b><small>{h.subtitle||''}</small></span>
      </div>
    {/if}
    {#each $contextMenuState.items as item}
      {#if item === null}
        <div class="border-t border-white/5 my-1"></div>
      {:else if item.type==='rating'}
        <div class="rating" role="group" aria-label="Valoración">
          <i aria-hidden="true" class="ph ph-star text-base shrink-0"></i><span class="label">Valoración</span>
          <span class="stars">
            {#each [1,2,3,4,5] as n}
              <button class="star" class:on={n<=item.value} aria-pressed={n===item.value}
                aria-label={n===item.value?`Quitar valoración de ${n} estrellas`:`Valorar con ${n} ${n===1?'estrella':'estrellas'}`}
                on:click={()=>rate(item,n)}><i aria-hidden="true" class="{n<=item.value?'ph-fill':'ph'} ph-star"></i></button>
            {/each}
          </span>
        </div>
      {:else}
        <button role="menuitem"
          class="item w-full flex items-center gap-3 px-4 text-left transition-colors {item.danger ? 'text-red-400 hover:bg-red-500/10' : 'text-armonia-text hover:bg-white/5'}"
          on:click={() => { closeContextMenu(); item.action(); }}
        >
          <i aria-hidden="true" class="{item.icon} text-base shrink-0" class:accent={item.active}></i>
          {item.label}
        </button>
      {/if}
    {/each}
  </div>
{/if}

<style>
  .scrim{display:none}
  .song-menu{max-height:80vh;overflow-y:auto}
  .item{padding-top:.6rem;padding-bottom:.6rem;font-size:.9rem}
  .accent{color:var(--color-armonia-accent)}
  .grip{display:none}
  .head{display:flex;align-items:center;gap:.75rem;padding:.6rem 1rem .7rem;border-bottom:1px solid #ffffff12;margin-bottom:.25rem}
  .art{width:44px;height:44px;border-radius:6px;background:#2a2433;display:grid;place-items:center;overflow:hidden;flex-shrink:0;color:#ffffff60}
  .art img{width:100%;height:100%;object-fit:cover}
  .who{display:flex;flex-direction:column;min-width:0}
  .who b{font-weight:600;font-size:.95rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:15rem}
  .who small{color:var(--color-armonia-muted);font-size:.8rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:15rem}
  .rating{display:flex;align-items:center;gap:.75rem;padding:.25rem .5rem .25rem 1rem;font-size:.9rem}
  .rating .label{flex:1}
  .stars{display:flex}
  .star{width:34px;height:38px;display:grid;place-items:center;color:#ffffff55;font-size:1.15rem;border-radius:6px}
  .star.on{color:var(--color-armonia-accent)}
  .star:hover{color:#fff}
  @media(max-width:767px){
    .scrim{display:block;position:fixed;inset:0;z-index:199;background:#0009}
    .song-menu{top:auto !important;bottom:0;left:0 !important;width:100%;border-radius:1rem 1rem 0 0;padding-bottom:max(.5rem,env(safe-area-inset-bottom));max-height:80dvh;background:#1f1c26}
    .grip{display:block;width:40px;height:4px;border-radius:2px;background:#ffffff35;margin:.5rem auto .25rem}
    .head{padding:.5rem 1.25rem 1rem}.art{width:52px;height:52px}.who b,.who small{max-width:70vw}
    .item{padding:.95rem 1.25rem;font-size:1rem;gap:1rem}.item i{font-size:1.35rem}
    .rating{padding:.4rem .75rem .4rem 1.25rem;font-size:1rem;gap:1rem}.rating>i{font-size:1.35rem}
    .star{width:40px;height:44px;font-size:1.4rem}
  }
</style>
