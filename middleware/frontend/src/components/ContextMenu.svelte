<script>
  import { contextMenuState,closeContextMenu } from '../lib/stores/contextMenuStore.js';
  import {tick} from 'svelte';
  import {cubicOut} from 'svelte/easing';
  import {fade} from 'svelte/transition';
  import MaterialIcon from './MaterialIcon.svelte';
  let menu;
  // A phone (or a narrow window) shows the app's menus: a DropdownMenu floating by the button,
  // or the bottom sheet when the caller asks for it. A wide window keeps the desktop menu.
  const narrowNow=()=>typeof matchMedia==='function'&&matchMedia('(max-width: 767px)').matches;
  $: state=$contextMenuState;
  $: mode=!state.visible?null:!narrowNow()?'desktop':state.sheet?'sheet':'popup';
  // The keyboard starts on the first entry; a finger does not need it (and the app shows no focus ring).
  $: if(mode==='desktop')tick().then(()=>menu?.querySelector('button:not(:disabled)')?.focus({preventScroll:true}));
  function keys(e){
    if(e.key==='Escape')closeContextMenu();
    if(['ArrowDown','ArrowUp'].includes(e.key)){
      e.preventDefault();
      const buttons=[...menu.querySelectorAll('button[role=menuitem]:not(:disabled),button.star:first-of-type')],i=buttons.indexOf(document.activeElement);
      buttons[(i+(e.key==='ArrowDown'?1:buttons.length-1))%buttons.length]?.focus();
    }
  }
  // A rating stays in the menu: the stars change in place so the choice is visible before closing.
  async function rate(item,value){
    const next=item.value===value?0:value,before=item.value;
    item.value=next;contextMenuState.update(s=>s);
    try{await item.onRate(next);}catch{item.value=before;contextMenuState.update(s=>s);}
  }
  function choose(item){closeContextMenu();item.action();}

  // Where Compose puts a DropdownMenu: below the button, else above it, else centred on it, else
  // against the bottom margin; to the right of the button's start when it is on the left half of
  // the screen, to the left of its end otherwise. It grows from the side nearest the button.
  const MARGIN=48;
  function place(node,rect){
    const W=innerWidth,H=innerHeight;
    node.style.maxHeight=(H-2*MARGIN)+'px';
    const w=node.offsetWidth,h=Math.min(node.offsetHeight,H-2*MARGIN);
    const xs=rect.left<W/2?[rect.left,rect.right-w,W-w]:[rect.right-w,rect.left,0];
    const x=xs.find(v=>v>=0&&v+w<=W)??0;
    const y=[rect.bottom,rect.top-h,rect.top-h/2,H-h-MARGIN].find(v=>v>=MARGIN&&v+h<=H-MARGIN)??Math.max(MARGIN,rect.top-h);
    node.style.left=x+'px';node.style.top=y+'px';
    const ox=Math.min(Math.max(rect.left+rect.width/2-x,0),w),oy=Math.min(Math.max(rect.top+rect.height/2-y,0),h);
    node.style.transformOrigin=`${ox}px ${oy}px`;
  }
  // Material 3 timings: in 120 ms from 80 % size (fully opaque after the first quarter), out in 75 ms.
  const popIn=()=>({duration:120,easing:cubicOut,css:t=>`opacity:${Math.min(1,t*4)};transform:scale(${.8+.2*t})`});
  const popOut=()=>({duration:75,css:t=>`opacity:${t};transform:scale(${.8+.2*t})`});
  // Only the bottom sheet slides; the desktop menu appears and goes at once. `shown` outlives the
  // closing, so the sheet still knows to slide away.
  let shown=null;
  $: if(mode)shown=mode;
  const rise=()=>shown==='sheet'?{duration:250,easing:cubicOut,css:(t,u)=>`transform:translateY(${u*100}%)`}:{duration:0};
  const sink=()=>shown==='sheet'?{duration:200,css:(t,u)=>`transform:translateY(${u*100}%)`}:{duration:0};
</script>

{#if mode==='popup'}
  <button class="scrim" aria-label="Cerrar menu" tabindex="-1" on:click={closeContextMenu}></button>
  <!-- svelte-ignore a11y-click-events-have-key-events -->
  <div bind:this={menu} class="popup" role="menu" tabindex="-1" aria-label={state.header?`Acciones de ${state.header.title}`:'Acciones'}
    use:place={state.rect} in:popIn out:popOut on:keydown={keys} on:click|stopPropagation>
    {#if state.header}
      <div class="p-head"><b>{state.header.title}</b>{#if state.header.subtitle}<small>{state.header.subtitle}</small>{/if}</div>
      <div class="p-divider"></div>
    {/if}
    {#each state.items as item}
      {#if item === null}
        <div class="p-divider"></div>
      {:else if item.type==='rating'}
        <div class="p-stars" role="group" aria-label="Valoracion">
          {#each [1,2,3,4,5] as n}
            <button class="star" class:on={n<=item.value} aria-pressed={n===item.value}
              aria-label={n===item.value?`Quitar valoracion de ${n} estrellas`:`Valorar con ${n} ${n===1?'estrella':'estrellas'}`}
              on:click={()=>rate(item,n)}><MaterialIcon name={n<=item.value?'star':'star_border'} /></button>
          {/each}
        </div>
      {:else}
        <button role="menuitem" class="p-item" class:danger={item.danger} disabled={item.disabled} on:click={()=>choose(item)}>
          {#if item.micon}<MaterialIcon name={item.micon} />{:else if item.icon}<i aria-hidden="true" class="{item.icon} p-ph"></i>{/if}
          <span>{item.label}</span>
        </button>
      {/if}
    {/each}
  </div>
{:else if mode}
  {#if mode==='sheet'}<button class="scrim dim" aria-label="Cerrar menu" tabindex="-1" on:click={closeContextMenu} transition:fade={{duration:200}}></button>{/if}
  <!-- svelte-ignore a11y-click-events-have-key-events -->
  <div
    bind:this={menu} role="menu" aria-label={state.header?`Acciones de ${state.header.title}`:'Acciones'} tabindex="-1"
    on:keydown={keys} on:click|stopPropagation
    class="song-menu fixed z-200 bg-armonia-surface border border-white/10 rounded-xl shadow-2xl py-1 min-w-[240px]"
    class:sheet={mode==='sheet'}
    style:top={mode==='sheet'?null:`${state.y}px`}
    style:left={mode==='sheet'?null:`${state.x}px`}
    in:rise={{}} out:sink={{}}
  >
    {#if state.header}
      {@const h=state.header}
      <div class="grip" aria-hidden="true"></div>
      <div class="head">
        <span class="art">{#if h.art}<img src={h.art} alt="" referrerpolicy="no-referrer" on:error={e=>e.currentTarget.style.visibility='hidden'}>{:else}<i aria-hidden="true" class="ph ph-music-note"></i>{/if}</span>
        <span class="who"><b>{h.title}</b><small>{h.subtitle||''}</small></span>
      </div>
    {/if}
    {#each state.items as item}
      {#if item === null}
        <div class="border-t border-white/5 my-1"></div>
      {:else if item.type==='rating'}
        <div class="rating" role="group" aria-label="Valoracion">
          <i aria-hidden="true" class="ph ph-star text-base shrink-0"></i><span class="label">Valoracion</span>
          <span class="stars">
            {#each [1,2,3,4,5] as n}
              <button class="star" class:on={n<=item.value} aria-pressed={n===item.value}
                aria-label={n===item.value?`Quitar valoracion de ${n} estrellas`:`Valorar con ${n} ${n===1?'estrella':'estrellas'}`}
                on:click={()=>rate(item,n)}><i aria-hidden="true" class="{n<=item.value?'ph-fill':'ph'} ph-star"></i></button>
            {/each}
          </span>
        </div>
      {:else}
        <button role="menuitem" disabled={item.disabled}
          class="item w-full flex items-center gap-3 px-4 text-left transition-colors {item.danger ? 'text-red-400 hover:bg-red-500/10' : 'text-armonia-text hover:bg-white/5'}"
          on:click={() => choose(item)}
        >
          {#if item.micon}<MaterialIcon name={item.micon} size={20} />{:else}<i aria-hidden="true" class="{item.icon} text-base shrink-0" class:accent={item.active}></i>{/if}
          {item.label}
        </button>
      {/if}
    {/each}
  </div>
{/if}

<style>
  .scrim{position:fixed;inset:0;z-index:199;background:transparent;cursor:default}
  .scrim.dim{background:#0009}

  /* The app's DropdownMenu: surfaceContainer, 4 dp corners, 8 dp padding, 48 dp rows, 112–280 dp wide. */
  .popup{position:fixed;z-index:200;min-width:112px;max-width:280px;width:max-content;overflow-y:auto;padding:8px 0;border-radius:4px;
    background:#181818;color:#eee;box-shadow:0 2px 6px 2px #00000026,0 1px 2px #0000004d}
  .p-head{display:flex;flex-direction:column;padding:8px 12px;max-width:280px}
  .p-head b{font-size:14px;line-height:20px;font-weight:500;letter-spacing:.1px}
  .p-head small{font-size:12px;line-height:16px;letter-spacing:.4px;color:#eeeeeea6}
  .p-divider{height:1px;background:#222}
  .p-item{display:flex;align-items:center;gap:12px;width:100%;min-height:48px;padding:0 12px;text-align:left;font-size:14px;line-height:20px;font-weight:500;letter-spacing:.1px;color:#eee}
  .p-item:disabled{opacity:.38}
  .p-item.danger{color:#ff5449}
  .p-ph{font-size:24px;width:24px;flex:none}
  .p-stars{display:flex;padding:0 8px}
  .p-stars .star{width:40px;height:40px;display:grid;place-items:center;border-radius:50%;color:#eeeeee80}
  .p-stars .star.on{color:var(--color-armonia-accent,#c4a3ff)}

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
  /* The bottom sheet (SongMenuSheet). */
  .song-menu.sheet{top:auto;bottom:0;left:0;width:100%;border-radius:1rem 1rem 0 0;padding-bottom:max(.5rem,env(safe-area-inset-bottom));max-height:80dvh;background:#1f1c26}
  .sheet .grip{display:block;width:40px;height:4px;border-radius:2px;background:#ffffff35;margin:.5rem auto .25rem}
  .sheet .head{padding:.5rem 1.25rem 1rem}.sheet .art{width:52px;height:52px}.sheet .who b,.sheet .who small{max-width:70vw}
  .sheet .item{padding:.95rem 1.25rem;font-size:1rem;gap:1rem}.sheet .item i{font-size:1.35rem}
  .sheet .rating{padding:.4rem .75rem .4rem 1.25rem;font-size:1rem;gap:1rem}.sheet .rating>i{font-size:1.35rem}
  .sheet .star{width:40px;height:44px;font-size:1.4rem}
</style>
