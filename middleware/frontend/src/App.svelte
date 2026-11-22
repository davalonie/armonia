<script>
  import { onMount,tick } from 'svelte';
  import { getSession, setSession, me } from './lib/api.js';
  import { currentView, showView } from './lib/stores/viewStore.js';
  import { initAudio, loadPlaybackSettings } from './lib/stores/playerStore.js';
  import { currentTrack } from './lib/stores/playerStore.js';

  import Login from './auth/Login.svelte';
  import Sidebar from './components/Sidebar.svelte';
  import MobileNav from './components/MobileNav.svelte';
  import MiniPlayer from './components/MiniPlayer.svelte';
  import ExpandedPlayer from './components/ExpandedPlayer.svelte';
  import QueuePanel from './components/QueuePanel.svelte';
  import ContextMenu from './components/ContextMenu.svelte';
  import Toasts from './components/Toasts.svelte';
  import PlaylistPicker from './components/PlaylistPicker.svelte';
  import SaveSheet from './components/SaveSheet.svelte';

  import Home from './views/Home.svelte';
  import Collection from './views/Collection.svelte';
  import ManualInbox from './views/ManualInbox.svelte';
  import ImportAll from './views/ImportAll.svelte';
  import {hasPendingLogin} from './lib/spotifyLogin.js';
  import More from './views/More.svelte';
  import Search from './views/Search.svelte';
  import Liked from './views/Liked.svelte';
  import Artists from './views/Artists.svelte';
  import Playlists from './views/Playlists.svelte';
  import Downloads from './views/Downloads.svelte';
  import Settings from './views/Settings.svelte';
  import MixedPlaylists from './views/MixedPlaylists.svelte';
  import Listening from './views/Listening.svelte';

  const VIEWS = {
    home: Home, more: More, search: Search, library: Collection, liked: Liked, artists: Artists,
    playlists: Playlists, jobs: Downloads, settings: Settings,
    mixed: MixedPlaylists, listening: Listening,
    'manual-inbox': ManualInbox, 'import-all': ImportAll,
  };

  let mainEl, displayed=null;
  const scrollOffsets={};
  $: if(mainEl && displayed!==$currentView){
    if(displayed)scrollOffsets[displayed]=mainEl.scrollTop;
    displayed=$currentView;
    const view=displayed;tick().then(()=>{if(displayed===view)mainEl.scrollTop=scrollOffsets[view]||0;});
  }
  let visited=new Set();
  $: visited=new Set([...visited,$currentView]);
  let authed = false;
  let checking = true;
  let checkError = '';
  let audioEl;
  let audioInitialized = false;

  async function checkSession() {
    checking=true;
    checkError='';
    const session = getSession();
    if (!session) { checking = false; return; }
    try {
      setSession(await me());
      authed = true;
    } catch (error) {
      if ([401,409].includes(error.status)) setSession(null);
      else checkError='No se pudo verificar la sesión. Comprueba la conexión y vuelve a intentarlo.';
    }
    checking = false;
  }
  onMount(() => {
    const changed=e=>{if(e.key==='armonia.session')location.reload();};
    window.addEventListener('storage',changed);
    // Returning from Spotify's sign-in: that view finishes it and clears the address.
    if(hasPendingLogin()&&/[?&](code|error)=/.test(location.search))showView('import-all');
    // The Android app links here; the marker is dropped so a reload keeps whatever view is current.
    if(new URLSearchParams(location.search).get('abrir')==='importar-todo'){showView('import-all');history.replaceState(null,'',location.pathname);}
    void checkSession();
    return ()=>window.removeEventListener('storage',changed);
  });

  function onLoginSuccess() { authed = true; }

  $: if (authed && audioEl && !audioInitialized) {
    audioInitialized = true;
    initAudio(audioEl);
    void loadPlaybackSettings();
  }

  // Toggle body class so CSS can adjust view padding when player is visible
  $: if (typeof document !== 'undefined') {
    document.body.classList.toggle('player-visible', !!$currentTrack);
  }
</script>

{#if checking}
  <div class="fixed inset-0 bg-armonia-bg flex items-center justify-center">
    <img src="/armonia.svg" alt="" class="w-12 h-12 rounded-xl animate-pulse" draggable="false">
  </div>
{:else if checkError}
  <section class="music-page"><p role="alert">{checkError}</p><button on:click={checkSession}>Reintentar conexión</button></section>
{:else if !authed}
  <Login on:success={onLoginSuccess} />
{:else}
  <div class="bg-armonia-bg text-armonia-text font-sans h-screen w-full overflow-hidden flex flex-col selection:bg-armonia-accent selection:text-white antialiased">
    <div class="flex-1 flex overflow-hidden">
      <Sidebar />
      <main bind:this={mainEl} class="flex-1 overflow-y-auto h-full md:pb-28 relative w-full" id="view">
        {#each Object.entries(VIEWS) as [view,component]}
          {#if visited.has(view)}<div hidden={$currentView!==view}><svelte:component this={component} /></div>{/if}
        {/each}
      </main>
    </div>

    <MobileNav />
    <MiniPlayer />
    <ExpandedPlayer />
    <QueuePanel />

    <ContextMenu />
    <PlaylistPicker />
    <SaveSheet />

    <div id="toast-container" class="fixed top-4 right-4 z-300 flex flex-col gap-2 pointer-events-none">
      <Toasts />
    </div>

    <audio bind:this={audioEl} preload="metadata" id="audio"></audio>
  </div>
{/if}

<style>
  :global(body) { margin: 0; padding: 0; }
  :global(#app) { height: 100vh; overflow: hidden; }
</style>
