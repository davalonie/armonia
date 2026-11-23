<script>
  import { APP_NAME } from '../lib/brand.js';
  import { onMount } from 'svelte';
  import { currentView, showView, isMoreView } from '../lib/stores/viewStore.js';

  const COLLAPSED_KEY = 'armonia:sidebar-collapsed';

  let collapsed = localStorage.getItem(COLLAPSED_KEY) === '1';
  let mounted = false;

  onMount(() => { mounted = true; });

  function toggle() {
    collapsed = !collapsed;
    localStorage.setItem(COLLAPSED_KEY, collapsed ? '1' : '0');
  }

  const NAV = [
    {view:'home',icon:'ph-house',label:'Inicio'},
    {view:'search',icon:'ph-magnifying-glass',label:'Buscar'},
    {view:'library',icon:'ph-books',label:'Biblioteca'},
    {view:'more',icon:'ph-dots-three',label:'Mas'},
  ];
  const NAV_BOTTOM = [];
</script>

<aside
  class="hidden md:flex flex-col bg-armonia-bg border-r border-white/5 h-full pt-8 pb-28 user-select-none overflow-hidden"
  style:width={collapsed ? '64px' : '256px'}
  style:transition={mounted ? 'width 200ms ease-in-out' : 'none'}
>
  <!-- Logo + toggle -->
  <div class="flex items-center gap-3 px-5 mb-10 min-w-0">
    <button
      on:click={toggle}
      class="w-8 h-8 shrink-0 rounded-lg overflow-hidden hover:opacity-85 transition-opacity"
      title={collapsed ? 'Mostrar el menu' : 'Plegar el menu'}
      aria-label={collapsed ? 'Mostrar el menu' : 'Plegar el menu'}
    >
      <img src="/armonia.svg" alt="" class="w-8 h-8" draggable="false">
    </button>
    <h1
      class="font-london text-3xl whitespace-nowrap overflow-hidden"
      style:opacity={collapsed ? '0' : '1'}
      style:max-width={collapsed ? '0' : '200px'}
      style:transition={mounted ? 'opacity 200ms, max-width 200ms' : 'none'}
    >{APP_NAME}</h1>
  </div>

  <!-- Navigation -->
  <nav class="flex flex-col gap-1 flex-1 px-2">
    {#each NAV as item}
      <button
        aria-label={item.label}
        on:click={() => showView(item.view)}
        class="flex items-center gap-4 px-3 py-3 rounded-xl transition-all text-left font-medium min-w-0 hover:bg-white/5 hover:text-armonia-text {$currentView === item.view || (item.view === 'library' && $currentView === 'import-all') || (item.view === 'more' && isMoreView($currentView)) ? 'text-armonia-text bg-white/5' : 'text-armonia-muted'}"
      >
        <i aria-hidden="true" class="ph {item.icon} text-2xl shrink-0"></i>
        <span
          class="whitespace-nowrap overflow-hidden"
          style:opacity={collapsed ? '0' : '1'}
          style:max-width={collapsed ? '0' : '200px'}
          style:transition={mounted ? 'opacity 200ms, max-width 200ms' : 'none'}
        >{item.label}</span>
      </button>
    {/each}

    <div class="flex-1"></div>

    {#each NAV_BOTTOM as item}
      <button
        aria-label={item.label}
        on:click={() => showView(item.view)}
        class="flex items-center gap-4 px-3 py-3 rounded-xl transition-all text-left font-medium min-w-0 hover:bg-white/5 hover:text-armonia-text {$currentView === item.view ? 'text-armonia-text bg-white/5' : 'text-armonia-muted'}"
      >
        <i aria-hidden="true" class="ph {item.icon} text-2xl shrink-0"></i>
        <span
          class="whitespace-nowrap overflow-hidden"
          style:opacity={collapsed ? '0' : '1'}
          style:max-width={collapsed ? '0' : '200px'}
          style:transition={mounted ? 'opacity 200ms, max-width 200ms' : 'none'}
        >{item.label}</span>
      </button>
    {/each}
  </nav>
</aside>
