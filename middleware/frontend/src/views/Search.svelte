<script>
  import {searchFor} from '../lib/stores/viewStore.js';
  // Buscar: one field over the user's library (songs, albums, artists, playlists) and the permitted
  // external catalogue. Results are music rows with artwork; everything plays through the shared queue.
  import {onDestroy,onMount} from 'svelte';
  import {currentView} from '../lib/stores/viewStore.js';
  import {librarySongs,recentlyAdded} from '../lib/librarySongs.js';
  import {searchSource} from '../lib/searchSource.js';
  import {songMenu} from '../lib/trackActions.js';
  import {search as searchApi,library,coverArtUrl,getSession} from '../lib/api.js';
  import {playQueue,playNext,undoPlayNext,prepareTrack,currentTrack,playing} from '../lib/stores/playerStore.js';
  import {accountKey,api,toQueueTrack} from '../lib/homelab.js';
  import {loaders,context,count,albumEntry,playlistEntry} from '../lib/lists.js';
  import {showToast} from '../lib/stores/toastStore.js';
  import {trackJob} from '../lib/jobs.js';
  import Cover from '../components/Cover.svelte';
  import PlaylistDetail from '../components/PlaylistDetail.svelte';
  import DownloadDialog from '../components/DownloadDialog.svelte';
  import ArtistPage from '../components/ArtistPage.svelte';
  import AlbumPage from '../components/AlbumPage.svelte';

  const HISTORY_KEY=`armonia:search-history:${accountKey()}`;
  const FILTERS=[['todo','Todo'],['canciones','Canciones'],['artistas','Artistas'],['albumes','Albumes'],['playlists','Playlists']];
  let query='',filter='todo',inputEl,timer=null,controller=null,run=0;
  let searched='',loading=false,error='',externalError=false;
  let local={songs:[],albums:[],artists:[]},external={songs:[],artists:[]},playlists=[];
  let ownPlaylists=null,ownLoadedAt=0;
  let stack=[];   // drill-down pages; the results stay underneath with their query and scroll
  let history=readHistory();
  let dl={open:false,videoId:'',artist:'',title:'',album:''};

  function readHistory(){try{return JSON.parse(localStorage.getItem(HISTORY_KEY)||'[]');}catch{return [];}}
  function remember(q){history=[q,...readHistory().filter(x=>x!==q)].slice(0,12);localStorage.setItem(HISTORY_KEY,JSON.stringify(history));}
  function forget(q){history=readHistory().filter(x=>x!==q);localStorage.setItem(HISTORY_KEY,JSON.stringify(history));}

  const externalSong=r=>toQueueTrack({source:'youtube',source_id:r.videoId,title:r.title||'Sin titulo',artist:r.channel||'Desconocido',album:r.album||'',duration:r.duration||null},r.thumbnail||null);
  const fold=s=>s.normalize('NFKD').replace(/[̀-ͯ]/g,'').toLowerCase();

  async function loadOwnPlaylists(signal){
    if(ownPlaylists&&Date.now()-ownLoadedAt<60000)return ownPlaylists;
    const [nativeLists,mixed]=await Promise.all([library('getPlaylists',{},{signal}),api.playlists().catch(()=>({playlists:[]}))]);
    const me=getSession()?.username;
    ownPlaylists=[...(nativeLists.playlists?.playlist||[]).filter(p=>!p.owner||p.owner===me).map(p=>({...p,kind:'local'})),
      ...mixed.playlists.map(p=>({...p,kind:'mixed'}))];
    ownLoadedAt=Date.now();
    return ownPlaylists;
  }

  // Typing schedules a search; a newer one aborts the requests of the previous and ignores late answers.
  function schedule(){
    clearTimeout(timer);
    const q=query.trim();
    if(q.length<2){cancel();searched='';error='';loading=false;return;}
    timer=setTimeout(()=>go(false),350);
  }
  function cancel(){run++;controller?.abort();controller=null;}
  // Another screen asked to search something (statistics → an artist).
  onMount(()=>searchFor.subscribe(text=>{if(!text)return;searchFor.set('');query=text;void go();}));
  async function go(save=true){
    clearTimeout(timer);
    const q=query.trim();
    if(q.length<2)return;
    if(save)remember(q);
    if(q===searched&&!error&&!externalError&&!loading)return;
    cancel();
    const mine=run;controller=new AbortController();const signal=controller.signal;
    loading=true;error='';externalError=false;stack=[];
    searched=q;local={songs:[],albums:[],artists:[]};external={songs:[],artists:[]};playlists=[];
    const source=searchSource();
    const [lib,ext,artists]=await Promise.allSettled([
      library('search3',{query:q,songCount:12,albumCount:8,artistCount:6},{signal}).then(r=>{
        if(mine!==run)return;
        const found=r.searchResult3||{};
        local={songs:found.song||[],albums:found.album||[],artists:found.artist||[]};
      }),
      searchApi(q,15,source,signal,"songs").then(r=>{
        if(mine!==run)return;
        external={...external,songs:r.songs||[]};
        if(external.songs[0])prepareTrack(externalSong(external.songs[0]));
      }),
      source==="youtube_music" && searchApi(q,15,source,signal,"artists").then(r=>{
        if(mine===run)external={...external,artists:r.artists||[]};
      }),
      loadOwnPlaylists(signal).then(rows=>{
        if(mine===run)playlists=rows.filter(p=>fold(p.name).includes(fold(q))).slice(0,8);
      })]);
    if(mine!==run)return;
    loading=false;
    externalError=[ext,artists].some(r=>r.status==='rejected'&&r.reason?.status!==403);
    if(lib.status==='rejected'&&ext.status==='rejected')error=lib.reason?.message||'No se pudo buscar. Vuelve a intentarlo.';
  }
  onDestroy(()=>{clearTimeout(timer);cancel();});
  // «Añadidas recientemente»: the 20 newest songs of the library, as in the app. Read again each time Buscar opens.
  let recent=[];
  async function loadRecent(){try{recent=recentlyAdded(await librarySongs());}catch{/* the section just stays hidden */}}
  onMount(()=>currentView.subscribe(view=>{if(view==='search')void loadRecent();}));
  function playRecent(i){playQueue(recent.map(s=>({...s,_from:'Añadidas recientemente'})),i);}

  $: shown={
    songs:filter==='todo'||filter==='canciones',artists:filter==='todo'||filter==='artistas',
    albums:filter==='todo'||filter==='albumes',playlists:filter==='todo'||filter==='playlists'};
  $: limit=filter==='todo'?4:50;
  $: empty=searched&&!loading&&!error&&!(local.songs.length+local.albums.length+local.artists.length+external.songs.length+external.artists.length+playlists.length);
  $: emptyFilter=searched&&!loading&&!empty&&!error&&(
    (filter==='canciones'&&!local.songs.length&&!external.songs.length)||(filter==='artistas'&&!local.artists.length&&!external.artists.length)||
    (filter==='albumes'&&!local.albums.length)||(filter==='playlists'&&!playlists.length));

  // --- actions ---
  function playLocal(i){playQueue([{...local.songs[i],_from:`Busqueda: ${searched}`}]);}
  function playExternal(i){playQueue([{...externalSong(external.songs[i]),_from:`Busqueda: ${searched}`}]);}
  function enqueue(song){const token=playNext(song);showToast('Se reproducira a continuacion','info',()=>undoPlayNext(token));}
  function externalActions(r){return [{label:'Descargar a la biblioteca',icon:'ph ph-download-simple',action:()=>dl={open:true,videoId:r.videoId,artist:r.channel||'',title:r.title||'',album:r.album||''}}];}

  // Dragging a song row to the right queues it right after the current song, without interrupting it.
  let drag=null,suppressClickUntil=0;
  function dragStart(e,key){if(e.target.closest('button.icon'))return;drag={key,x:e.clientX,y:e.clientY,dx:0};}
  function dragMove(e){
    if(!drag)return;
    const dx=e.clientX-drag.x,dy=e.clientY-drag.y;
    if(Math.abs(dy)>30&&Math.abs(dy)>Math.abs(dx)){drag=null;return;}
    drag={...drag,dx:Math.max(0,Math.min(dx,120))};
  }
  function dragEnd(song){
    if(!drag)return;
    if(drag.dx>72){enqueue(song);suppressClickUntil=Date.now()+500;}
    drag=null;
  }
  const guarded=fn=>()=>{if(Date.now()>suppressClickUntil)fn();};

  // --- drill-down ---
  let token=0;
  async function openList(entry){
    const mine=++token;
    stack=[...stack,{kind:'list',entry,rows:[],loading:true,notice:''}];
    try{
      const data=await loaders[entry.type](entry);
      if(mine!==token)return;
      stack=stack.map(p=>p.entry===entry?{...p,rows:data.rows,loading:false,meta:count(data.rows.length)}:p);
    }catch(e){if(mine===token)stack=stack.map(p=>p.entry===entry?{...p,loading:false,notice:e.message}:p);}
  }
  async function openLocalArtist(artist){
    const mine=++token;
    stack=[...stack,{kind:'artist',artist,albums:[],loading:true,notice:''}];
    try{
      const data=await library('getArtist',{id:artist.id});
      if(mine===token)stack=stack.map(p=>p.artist===artist?{...p,albums:data.artist?.album||[],loading:false}:p);
    }catch(e){if(mine===token)stack=stack.map(p=>p.artist===artist?{...p,loading:false,notice:e.message}:p);}
  }
  const back=()=>{token++;stack=stack.slice(0,-1);};
</script>

{#if stack.length}
  {@const top=stack[stack.length-1]}
  {#if top.kind==='list'}
    <PlaylistDetail title={top.entry.title} eyebrow={top.entry.eyebrow} description={top.entry.description||''} meta={top.meta||''}
      covers={top.entry.covers||[]} variant="plain" rows={top.rows} context={context(top.entry)} loading={top.loading} notice={top.notice}
      on:back={back}><div slot="empty"><p>Esta lista no tiene canciones todavia.</p></div></PlaylistDetail>
  {:else if top.kind==='artist'}
    <div class="search subpage">
      <button class="back" aria-label="Volver" on:click={back}><i aria-hidden="true" class="ph ph-arrow-left"></i></button>
      <p class="eyebrow">Artista de tu biblioteca</p>
      <h1>{top.artist.name}</h1>
      {#if top.loading}<p class="hint" role="status">Cargando albumes…</p>
      {:else if top.notice}<p class="hint" role="alert">{top.notice}</p>
      {:else if !top.albums.length}<p class="hint">No hay albumes de este artista en tu biblioteca.</p>
      {:else}
        <ul class="rows">{#each top.albums as a (a.id)}
          <li><button class="row" aria-label={`Abrir ${a.name}`} on:click={()=>openList(albumEntry(a))}>
            <span class="art"><Cover covers={a.coverArt?[coverArtUrl(a.coverArt,96)]:[]} size={96} /></span>
            <span class="text"><b>{a.name}</b><small>Album{a.year?` · ${a.year}`:''}{a.songCount?` · ${count(a.songCount)}`:''}</small></span>
            <i aria-hidden="true" class="ph ph-caret-right chevron"></i></button></li>
        {/each}</ul>
      {/if}
    </div>
  {:else if top.kind==='ytartist'}
    <div class="search subpage"><ArtistPage channelId={top.id} source="youtube_music" on:back={back} on:album={e=>stack=[...stack,{kind:'ytalbum',id:e.detail.browseId}]} /></div>
  {:else}
    <div class="search subpage"><AlbumPage browseId={top.id} source="youtube_music" on:back={back} /></div>
  {/if}
{:else}
<div class="search">
  <h1>Buscar</h1>
  <form class="field" role="search" on:submit|preventDefault={()=>{inputEl?.blur();void go();}}>
    <i aria-hidden="true" class="ph-bold ph-magnifying-glass"></i>
    <input bind:this={inputEl} bind:value={query} type="search" enterkeyhint="search" autocomplete="off" autocapitalize="off" spellcheck="false"
      aria-label="Buscar canciones, artistas, albumes y playlists" placeholder="¿Que quieres escuchar?" on:input={schedule}>
    {#if query}<button type="button" class="clear" aria-label="Borrar busqueda" on:click={()=>{query='';schedule();inputEl?.focus();}}><i aria-hidden="true" class="ph ph-x"></i></button>{/if}
  </form>

  {#if searched||loading}
    <div class="chips" role="group" aria-label="Filtrar resultados">
      {#each FILTERS as [id,label]}<button class="chip" class:on={filter===id} aria-pressed={filter===id} on:click={()=>filter=id}>{label}</button>{/each}
    </div>
  {/if}

  {#if loading&&!(local.songs.length+local.artists.length+local.albums.length+external.songs.length+external.artists.length+playlists.length)}
    <div class="state" role="status"><i aria-hidden="true" class="ph ph-circle-notch spin"></i><p>Buscando…</p></div>
  {:else if error}
    <div class="state" role="alert"><i aria-hidden="true" class="ph ph-warning-circle"></i><p>{error}</p><button class="pill" on:click={()=>{searched='';void go();}}>Reintentar</button></div>
  {:else if !searched}
    {#if history.length||recent.length}
    {#if history.length}
      <section>
        <header class="section-head"><h2>Busquedas recientes</h2><button class="link" on:click={()=>{history=[];localStorage.removeItem(HISTORY_KEY);}}>Borrar todo</button></header>
        <ul class="rows">{#each history as h (h)}
          <li class="history"><button class="row" on:click={()=>{query=h;void go();}}><span class="art round"><i aria-hidden="true" class="ph ph-clock-counter-clockwise"></i></span><span class="text"><b>{h}</b></span></button>
            <button class="icon" aria-label={`Quitar ${h} de las busquedas recientes`} on:click={()=>forget(h)}><i aria-hidden="true" class="ph ph-x"></i></button></li>
        {/each}</ul>
      </section>
    {/if}
    {#if recent.length}
      <section>
        <header class="section-head"><h2>Añadidas recientemente</h2></header>
        <ul class="rows">{#each recent as s,i (s.id)}
          {@const active=$currentTrack?.id===s.id}
          <li class="recent"><button class="row" aria-label={`Reproducir ${s.title}`} on:click={()=>playRecent(i)}>
              <span class="art"><Cover covers={s.coverArt?[coverArtUrl(s.coverArt,96)]:[]} size={96} />{#if active}<span class="now" aria-hidden="true"><i class="ph-fill {$playing?'ph-speaker-high':'ph-pause'}"></i></span>{/if}</span>
              <span class="text"><b class:playing={active}>{s.title}</b><small>{s.artist}</small></span></button>
            <button class="icon" aria-label={`Opciones de ${s.title}`} on:click={e=>songMenu(e.currentTarget,s)}><i aria-hidden="true" class="ph ph-dots-three-vertical"></i></button></li>
        {/each}</ul>
      </section>
    {/if}
    {:else}
      <div class="state"><i aria-hidden="true" class="ph ph-magnifying-glass"></i><p>Busca en tu biblioteca y en las fuentes disponibles: canciones, artistas, albumes y playlists.</p></div>
    {/if}
  {:else if empty}
    <div class="state"><i aria-hidden="true" class="ph ph-magnifying-glass"></i><p>No hay resultados para «{searched}». Revisa la ortografia o prueba con otro titulo o artista.</p></div>
  {:else}
    <div class:stale={loading} aria-busy={loading}>
    {#if emptyFilter}<div class="state"><p>No hay {FILTERS.find(f=>f[0]===filter)[1].toLowerCase()} para «{searched}».</p></div>{/if}

    {#if shown.songs&&local.songs.length}
      <section><h2>Canciones en tu biblioteca</h2>
        <ul class="rows">{#each local.songs.slice(0,limit) as s,i (s.id)}
          {@const active=$currentTrack?.id===s.id}
          <li class="swipe" class:dragging={drag?.key==='l'+s.id}>
            <span class="swipe-hint" aria-hidden="true"><i class="ph ph-queue"></i> A continuacion</span>
            <!-- svelte-ignore a11y-no-static-element-interactions -->
            <div class="row-wrap" style:transform={drag?.key==='l'+s.id?`translateX(${drag.dx}px)`:''}
              on:pointerdown={e=>dragStart(e,'l'+s.id)} on:pointermove={dragMove} on:pointerup={()=>dragEnd(s)} on:pointercancel={()=>drag=null} on:dragstart|preventDefault>
              <button class="row" aria-label={`Reproducir ${s.title}`} on:click={guarded(()=>playLocal(i))}>
                <span class="art"><Cover covers={s.coverArt?[coverArtUrl(s.coverArt,96)]:[]} size={96} />{#if active}<span class="now" aria-hidden="true"><i class="ph-fill {$playing?'ph-speaker-high':'ph-pause'}"></i></span>{/if}</span>
                <span class="text"><b class:playing={active}>{s.title}</b><small>Cancion · {s.artist}</small></span></button>
              <button class="icon" aria-label={`Opciones de ${s.title}`} on:click={e=>songMenu(e.currentTarget,s)}><i aria-hidden="true" class="ph ph-dots-three-vertical"></i></button>
            </div></li>
        {/each}</ul>
      </section>
    {/if}

    {#if shown.artists&&(local.artists.length||external.artists.length)}
      <section><h2>Artistas</h2>
        <div class="shelf">
          {#each local.artists as a (a.id)}
            <button class="artist" aria-label={`Abrir ${a.name}`} on:click={()=>openLocalArtist(a)}>
              <Cover covers={a.coverArt?[coverArtUrl(a.coverArt,200)]:[]} variant="artist" size={200} /><b>{a.name}</b><small>En tu biblioteca</small></button>
          {/each}
          {#each external.artists as a (a.channelId)}
            <button class="artist" aria-label={`Abrir ${a.name}`} on:click={()=>stack=[...stack,{kind:'ytartist',id:a.channelId}]}>
              <Cover covers={a.thumbnail?[a.thumbnail]:[]} variant="artist" size={200} /><b>{a.name}</b><small>Artista</small></button>
          {/each}
        </div>
      </section>
    {/if}

    {#if shown.albums&&local.albums.length}
      <section><h2>Albumes</h2>
        <ul class="rows">{#each local.albums.slice(0,limit) as a (a.id)}
          <li><button class="row" aria-label={`Abrir ${a.name}`} on:click={()=>openList(albumEntry(a))}>
            <span class="art"><Cover covers={a.coverArt?[coverArtUrl(a.coverArt,96)]:[]} size={96} /></span>
            <span class="text"><b>{a.name}</b><small>Album · {a.artist}</small></span><i aria-hidden="true" class="ph ph-caret-right chevron"></i></button></li>
        {/each}</ul>
      </section>
    {/if}

    {#if shown.playlists&&playlists.length}
      <section><h2>Playlists</h2>
        <ul class="rows">{#each playlists.slice(0,limit) as p (p.kind+p.id)}
          {@const entry=playlistEntry(p)}
          <li><button class="row" aria-label={`Abrir ${p.name}`} on:click={()=>openList(entry)}>
            <span class="art"><Cover covers={entry.covers} size={96} /></span>
            <span class="text"><b>{p.name}</b><small>Playlist{entry.songs!=null?` · ${count(entry.songs)}`:''}</small></span><i aria-hidden="true" class="ph ph-caret-right chevron"></i></button></li>
        {/each}</ul>
      </section>
    {/if}

    {#if shown.songs&&external.songs.length}
      <section><h2>{local.songs.length?'Mas canciones':'Canciones'}</h2>
        <ul class="rows">{#each external.songs.slice(0,filter==='todo'?8:50) as r,i (r.videoId)}
          {@const song=externalSong(r)}
          {@const active=$currentTrack?.id===song.id}
          <li class="swipe" class:dragging={drag?.key==='e'+r.videoId}>
            <span class="swipe-hint" aria-hidden="true"><i class="ph ph-queue"></i> A continuacion</span>
            <!-- svelte-ignore a11y-no-static-element-interactions -->
            <div class="row-wrap" style:transform={drag?.key==='e'+r.videoId?`translateX(${drag.dx}px)`:''}
              on:pointerdown={e=>dragStart(e,'e'+r.videoId)} on:pointermove={dragMove} on:pointerup={()=>dragEnd(song)} on:pointercancel={()=>drag=null} on:dragstart|preventDefault>
              <button class="row" aria-label={`Reproducir ${r.title}`} on:click={guarded(()=>playExternal(i))}>
                <span class="art"><Cover covers={r.thumbnail?[r.thumbnail]:[]} size={96} />{#if active}<span class="now" aria-hidden="true"><i class="ph-fill {$playing?'ph-speaker-high':'ph-pause'}"></i></span>{/if}</span>
                <span class="text"><b class:playing={active}>{r.title||'Sin titulo'}</b><small>Cancion · {r.channel||'Desconocido'}</small></span></button>
              <button class="icon" aria-label={`Opciones de ${r.title}`} on:click={e=>songMenu(e.currentTarget,song,{extra:externalActions(r)})}><i aria-hidden="true" class="ph ph-dots-three-vertical"></i></button>
            </div></li>
        {/each}</ul>
      </section>
    {:else if shown.songs&&externalError}
      <p class="hint" role="status">La busqueda en fuentes externas no esta disponible ahora mismo. Se muestran solo los resultados de tu biblioteca.</p>
    {/if}
    </div>
  {/if}
</div>
{/if}

<DownloadDialog bind:open={dl.open} videoId={dl.videoId} bind:artist={dl.artist} bind:title={dl.title} bind:album={dl.album} source="youtube_music"
  on:download={e=>trackJob(e.detail.jobId,e.detail.artist,e.detail.title)} />

<style>
  .search{width:100%;max-width:1100px;margin:0 auto;padding:16px 16px 32px}
  @media(min-width:768px){.search{padding:28px 32px 40px}}
  h1{font-size:1.9rem;font-weight:800;margin:4px 0 14px}
  h2{font-size:1.2rem;font-weight:700;margin:0 0 6px}
  section{margin-top:26px}
  .section-head{display:flex;align-items:center;justify-content:space-between}
  .link{color:var(--color-armonia-muted);font-size:.85rem;padding:8px}
  .link:hover{color:#fff}
  .field{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:10px;background:#fff;color:#121015;border-radius:10px;padding:0 14px;height:52px;box-shadow:0 0 0 12px var(--color-armonia-bg)}
  .field:focus-within{outline:3px solid var(--color-armonia-accent);outline-offset:1px}
  .field>i{font-size:1.4rem}
  .field input{flex:1;min-width:0;height:100%;background:transparent;border:0;outline:0;font-size:1.05rem;font-weight:600;color:#121015}
  .field input::placeholder{color:#4a4553}
  .field input::-webkit-search-cancel-button{display:none}
  .clear{width:36px;height:36px;display:grid;place-items:center;border-radius:50%;color:#121015}
  .clear:hover{background:#0001}
  .chips{display:flex;gap:8px;overflow-x:auto;padding:18px 0 2px;scrollbar-width:none}
  .chip{flex-shrink:0;padding:8px 16px;border-radius:999px;background:#ffffff14;font-size:.9rem;font-weight:500}
  .chip.on{background:var(--color-armonia-accent);color:#121015;font-weight:700}
  .rows{list-style:none;margin:0;padding:0}
  .rows li{position:relative;display:flex;align-items:center;border-radius:8px}
  .row-wrap{position:relative;z-index:1;display:flex;align-items:center;flex:1;min-width:0;background:var(--color-armonia-bg);border-radius:8px;touch-action:pan-y;user-select:none;-webkit-user-select:none;transition:transform .15s}
  .dragging .row-wrap{transition:none}
  .swipe-hint{position:absolute;inset:0 auto 0 0;display:flex;align-items:center;gap:8px;padding-left:16px;color:var(--color-armonia-accent);font-size:.85rem;font-weight:600;opacity:0;pointer-events:none;z-index:0}
  .dragging .swipe-hint{opacity:1}
  .row{flex:1;min-width:0;display:flex;align-items:center;gap:12px;padding:7px 8px;border-radius:8px;text-align:left}
  .row:hover,.row:focus-visible{background:#ffffff0d}
  .art{position:relative;width:52px;height:52px;flex-shrink:0;display:block}
  .art.round{display:grid;place-items:center;border-radius:50%;background:#ffffff14;font-size:1.3rem;color:var(--color-armonia-muted)}
  .now{position:absolute;inset:0;display:grid;place-items:center;background:#0009;border-radius:6px;color:var(--color-armonia-accent);font-size:1.3rem}
  .text{flex:1;min-width:0;display:flex;flex-direction:column}
  .text b{font-weight:500;font-size:1rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .text b.playing{color:var(--color-armonia-accent)}
  .text small{color:var(--color-armonia-muted);font-size:.85rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .chevron{color:var(--color-armonia-muted)}
  .icon{width:44px;height:44px;flex-shrink:0;display:grid;place-items:center;border-radius:50%;color:var(--color-armonia-muted);font-size:1.3rem}
  .icon:hover{color:#fff;background:#ffffff14}
  .shelf{display:flex;gap:14px;overflow-x:auto;padding:6px 0 4px;scrollbar-width:thin}
  .artist{flex:0 0 112px;display:flex;flex-direction:column;align-items:center;gap:6px;padding:6px;border-radius:10px;text-align:center}
  .artist:hover{background:#ffffff0d}
  .artist b{font-size:.9rem;font-weight:600;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .artist small{font-size:.75rem;color:var(--color-armonia-muted)}
  @media(min-width:768px){.artist{flex-basis:148px}}
  .state{display:flex;flex-direction:column;align-items:center;gap:12px;padding:56px 16px;text-align:center;color:var(--color-armonia-muted)}
  .state i{font-size:2.6rem}
  .state p{max-width:34ch}
  .spin{animation:spin 1s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}
  .stale{opacity:.55;transition:opacity .2s}
  .hint{color:var(--color-armonia-muted);font-size:.9rem;margin-top:16px}
  .pill{padding:10px 20px;border-radius:999px;background:var(--color-armonia-accent);color:#121015;font-weight:700}
  .subpage{padding-top:12px}
  .back{width:40px;height:40px;display:grid;place-items:center;border-radius:50%;background:#ffffff14;font-size:1.2rem;margin-bottom:12px}
  .eyebrow{font-size:.75rem;letter-spacing:.08em;text-transform:uppercase;color:var(--color-armonia-muted);font-weight:600}
  .history .row{padding:9px 8px}
</style>
