<script>
  import { mobile, mobileLogin } from './lib/native.js';
  import {SEARCH_SOURCE_KEY} from './lib/searchSource.js';
  import { onMount,tick } from 'svelte';
  import { getSession, setSession, me } from './lib/api.js';
  import { currentView, showView } from './lib/stores/viewStore.js';
  import { initAudio, loadPlaybackSettings } from './lib/stores/playerStore.js';
  import { currentTrack,previewState } from './lib/stores/playerStore.js';

  import {expandedPlayerOpen,queuePanelOpen} from './lib/stores/uiStore.js';
  import {contextMenuState,closeContextMenu} from './lib/stores/contextMenuStore.js';
  import {saveSheet} from './lib/saveSong.js';
  import {playlistPickerState,closePlaylistPicker} from './lib/stores/playlistPickerStore.js';
  function phoneBack(event){
    const dialog=document.querySelector('dialog[open]');
    const pane=mainEl?.querySelector(':scope > div:not([hidden])');
    const back=pane?.querySelector('[data-phone-back], button[aria-label="Volver"]');
    if(dialog)dialog.close();
    else if($contextMenuState.visible)closeContextMenu();
    else if($saveSheet)saveSheet.set(null);
    else if($playlistPickerState.open)closePlaylistPicker();
    else if($queuePanelOpen)queuePanelOpen.set(false);
    else if($expandedPlayerOpen)expandedPlayerOpen.set(false);
    else if(back)back.click();
    else if($currentView!=='home')showView('home');
    else return;
    event.preventDefault();
  }

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
  import PhoneImport from './views/PhoneImport.svelte';
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
    ...(mobile?{'import-review':PhoneImport}:{}),
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
    // The phone's sign-in page: the native side opens the library once an account is in.
    if (mobileLogin) { checking = false; return; }
    if (mobile) {
      try {
        const identity=await mobile.identity();
        setSession(identity);
        // Probe the stored session without delaying offline startup. A 401 reaches the native interceptor.
        void mobile.request({path:'/api/me',method:'GET'}).catch(()=>{});
        localStorage.setItem(SEARCH_SOURCE_KEY,identity.searchSource);
        authed = true;
      } catch { checkError = 'No se pudo abrir la cuenta del dispositivo.'; }
      checking = false;
      return;
    }
    const returning = new URLSearchParams(location.search).get('oidc') === 'done';
    if (returning) {
      history.replaceState(null, '', location.pathname);
      setSession(null);
    }
    const session = getSession();
    if (!session && !returning) { checking = false; return; }
    try {
      setSession(await me());
      authed = true;
    } catch (error) {
      if ([401,409].includes(error.status)) setSession(null);
      else checkError='No se pudo verificar la sesion. Comprueba la conexion y vuelve a intentarlo.';
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
    if(mobile)window.addEventListener('armonia-back',phoneBack);
    void checkSession();
    return ()=>{window.removeEventListener('storage',changed);window.removeEventListener('armonia-back',phoneBack);};
  });

  function onLoginSuccess() { authed = true; }

  $: if (authed && (mobile || audioEl) && !audioInitialized) {
    audioInitialized = true;
    initAudio(audioEl);
    void loadPlaybackSettings();
  }

  // Toggle body class so CSS can adjust view padding when player is visible
  $: if (typeof document !== 'undefined') {
    document.body.classList.toggle('player-visible', !!$currentTrack && (!mobile || !$previewState));
  }
</script>

{#if checking}
  <div class="fixed inset-0 bg-armonia-bg flex items-center justify-center">
    <img src="/armonia.svg" alt="" class="w-12 h-12 rounded-xl animate-pulse" draggable="false">
  </div>
{:else if checkError}
  <section class="music-page"><p role="alert">{checkError}</p><button on:click={checkSession}>Reintentar conexion</button></section>
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
    {#if !mobile || !$previewState}<MiniPlayer />{/if}
    <ExpandedPlayer />
    <QueuePanel />

    <ContextMenu />
    <PlaylistPicker />
    <SaveSheet />

    <div id="toast-container" class="fixed top-4 right-4 z-300 flex flex-col gap-2 pointer-events-none">
      <Toasts />
    </div>

    {#if !mobile}<audio bind:this={audioEl} preload="metadata" id="audio"></audio>{/if}
  </div>
{/if}

<style>
  :global(body) { margin: 0; padding: 0; }
  :global(#app) { height: 100vh; overflow: hidden; }
</style>
