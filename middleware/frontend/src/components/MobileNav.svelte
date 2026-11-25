<script>
  import {tick} from 'svelte';
  import {mobile} from '../lib/native.js';
  import {currentView, showView, isMoreView} from '../lib/stores/viewStore.js';
  import More from '../views/More.svelte';
  import {PATHS} from './MaterialIcon.svelte';

  const tabs = [
    {view:'home',icon:'ph-house',label:'Inicio',path:'M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z'},
    {view:'search',icon:'ph-magnifying-glass',label:'Buscar',path:PATHS.search},
    {view:'library',icon:'ph-books',label:'Biblioteca',path:'M20 2H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2m-2 5h-3v5a3 3 0 1 1-2.99-3c.35 0 .68.06.99.17V5h5zM2 6v14c0 1.1.9 2 2 2h14v-2H4V6z'},
    {view:'more',icon:'ph-dots-three',label:'Mas',path:'M6 10a2 2 0 1 0 0 4 2 2 0 0 0 0-4m6 0a2 2 0 1 0 0 4 2 2 0 0 0 0-4m6 0a2 2 0 1 0 0 4 2 2 0 0 0 0-4'},
  ];
  let sheet, opened=false, dragY=0;
  async function navigate(view){
    if(mobile && view==='more'){
      opened=true;await tick();sheet.showModal();return;
    }
    showView(view);
    if(mobile && view==='search'){
      await tick();document.querySelector('#view [role="search"] input')?.focus();
    }
    if(mobile && view==='home')document.getElementById('view').scrollTop=0;
  }
</script>

<nav aria-label="Navegación principal" data-no-ripple class:phone={mobile} class="mobile-nav md:hidden fixed bottom-0 inset-x-0 z-40 bg-armonia-bg backdrop-blur-md border-t border-white/5 user-select-none" style="padding-bottom:env(safe-area-inset-bottom,0px)">
  <div class="flex items-stretch h-[60px]">
    {#each tabs as tab}
      {@const active = tab.view==='more' ? isMoreView($currentView) : $currentView===tab.view || (tab.view==='library' && $currentView==='import-all')}
      <button aria-current={active?'page':undefined} on:click={()=>navigate(tab.view)} class="flex flex-col items-center justify-center gap-0.5 flex-1 transition-colors {active?'text-armonia-accent':'text-armonia-muted'}">
        {#if mobile}<span class="nav-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d={tab.path}/></svg></span>
        {:else}<i aria-hidden="true" class="{active && tab.view!=='more'?'ph-fill':'ph'} {tab.icon} text-xl"></i>{/if}
        <span class="text-xs font-medium">{tab.label}</span>
      </button>
    {/each}
  </div>
</nav>

{#if mobile}
  <dialog class="more-sheet" bind:this={sheet} aria-label="Mas" on:close={()=>opened=false}
    on:click={e=>{if(e.target===sheet && e.clientY<sheet.getBoundingClientRect().top)sheet.close();}}>
    <button class="handle" aria-label="Cerrar hoja" on:click={()=>sheet.close()} on:touchstart={e=>dragY=e.touches[0].clientY}
      on:touchend={e=>{if(e.changedTouches[0].clientY-dragY>40)sheet.close();}}><span></span></button>
    {#if opened}<More asSheet={true} on:navigate={()=>sheet.close()} />{/if}
  </dialog>
{/if}

<style>
  .more-sheet{position:fixed;inset:auto 0 0;margin:0;width:100%;max-width:none;max-height:calc(100dvh - env(safe-area-inset-top));overflow:auto;border:0;border-radius:28px 28px 0 0;background:#211c29;color:#eee;padding:0 0 calc(16px + env(safe-area-inset-bottom,0px));font-family:var(--font-sans)}
  .more-sheet::backdrop{background:#0005}
  .handle{width:100%;height:48px;display:grid;place-items:center;touch-action:none}
  .handle span{width:32px;height:4px;border-radius:4px;background:#eee}
  .nav-icon{display:grid;place-items:center;width:60px;height:36px;border-radius:20px}
  button[aria-current] .nav-icon{background:#242424}
  .nav-icon svg{width:28px;height:28px;fill:currentColor}
  /* As NavigationBarItem in MainScreen.kt: unselected icon and label in onSurface at 60 %. */
  .phone button:not([aria-current]){color:#eeeeee99}
  button:last-child .nav-icon svg{width:24px}
</style>
