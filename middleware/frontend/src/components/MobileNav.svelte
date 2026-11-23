<script>
  import { currentView, showView, isMoreView } from '../lib/stores/viewStore.js';

  const TABS = [
    {view:'home',icon:'ph-house',label:'Inicio'},
    {view:'search',icon:'ph-magnifying-glass',label:'Buscar'},
    {view:'library',icon:'ph-books',label:'Biblioteca'},
  ];

  $: moreActive = isMoreView($currentView);
</script>

<nav
  class="md:hidden fixed bottom-0 inset-x-0 z-40 bg-armonia-bg backdrop-blur-md border-t border-white/5 user-select-none"
  style="padding-bottom: env(safe-area-inset-bottom, 0px)"
>
  <div class="flex items-stretch h-[60px]">
    {#each TABS as tab}
      {@const active = $currentView === tab.view || (tab.view === 'library' && $currentView === 'import-all')}
      <button
        on:click={() => showView(tab.view)}
        class="flex flex-col items-center justify-center gap-0.5 flex-1 transition-colors {active ? 'text-armonia-accent' : 'text-armonia-muted'}"
      >
        <i aria-hidden="true" class="{active ? 'ph-fill' : 'ph'} {tab.icon} text-xl"></i>
        <span class="text-xs font-medium">{tab.label}</span>
      </button>
    {/each}
    <button
      on:click={() => showView('more')}
      class="flex flex-col items-center justify-center gap-0.5 flex-1 transition-colors {moreActive ? 'text-armonia-accent' : 'text-armonia-muted'}"
    >
      <i aria-hidden="true" class="ph ph-dots-three text-xl"></i>
      <span class="text-xs font-medium">Mas</span>
    </button>
  </div>
</nav>
