<script>
  import {mobile} from '../lib/native.js';
  import PhonePlaylist from '../components/PhonePlaylist.svelte';
  import LibraryPlaylist from '../components/LibraryPlaylist.svelte';
  import PhoneDownloads from '../components/PhoneDownloads.svelte';
  import {albumList} from '../lib/albums.js';
  import {calendar,releaseEntry,releaseLine,releaseRows,releaseDay} from '../lib/releases.js';
  import {onMount} from 'svelte';
  import {get} from 'svelte/store';
  import {currentView,homeRoot} from '../lib/stores/viewStore.js';
  import {phoneOnline} from '../lib/stores/connection.js';
  import {coverArtUrl} from '../lib/api.js';
  import {api} from '../lib/homelab.js';
  import {loaders,context,count,likedEntry,albumEntry} from '../lib/lists.js';
  import {playList,beginPlayRequest,playQueue} from '../lib/stores/playerStore.js';
  import {showToast} from '../lib/stores/toastStore.js';
  import Cover from '../components/Cover.svelte';
  import PlaylistDetail from '../components/PlaylistDetail.svelte';
  import ArtistPage from '../components/ArtistPage.svelte';
  import AlbumPage from '../components/AlbumPage.svelte';

  let phone=null;
  // On the phone a library playlist opens the same screen as in Biblioteca.
  let libraryList=null;
  let recent=[],generated=[],status={},artists=[],frequent=[],newest=[];
  let loaded=false,homeError='',detail=null,pages=[],busy=false,poll=null,token=0;
  // «En el telefono» only without a connection (the user's choice, phone only): no network, or a server
  // that answers none of Inicio's requests (the same rule as «Copia guardada en el teléfono»).
  let serverDown=false;
  $: offline=!$phoneOnline||serverDown;
  let wasOnline=true;
  $: networkBack($phoneOnline);
  function networkBack(online){
    if(mobile&&online&&!wasOnline&&get(currentView)==='home')void loadHome();
    wasOnline=online;
  }

  const hour=new Date().getHours();
  const greeting=hour<6?'Buenas noches':hour<13?'Buenos dias':hour<21?'Buenas tardes':'Buenas noches';
  const liked=likedEntry;
  const day=seconds=>new Date(seconds*1000).toLocaleDateString('es-ES',{day:'numeric',month:'long'});
  const recentEntry=p=>({type:p.kind,id:p.id,title:p.name,covers:p.coverArt?[coverArtUrl(p.coverArt,160)]:(p.covers||[]),
    variant:p.kind==='generated'?(p.id==='weekly'?'weekly':'mix'):'plain',label:p.name.replace(/^Mix /,''),eyebrow:p.kind==='generated'?'Hecha para ti':'Lista'});
  const generatedEntry=g=>({type:'generated',id:g.key,title:g.name,covers:g.covers,variant:g.kind==='weekly'?'weekly':'mix',
    label:g.name.replace(/^Mix /,''),description:g.description,eyebrow:'Hecha para ti',state:g.state,count:g.count});

  async function loadHome(){
    const [r,g,a]=await Promise.allSettled([api.recent(),api.homePlaylists(),api.homeArtists()]);
    serverDown=[r,g,a].every(result=>result.status==='rejected');
    if(r.status==='fulfilled')recent=r.value.playlists;
    if(a.status==='fulfilled')artists=a.value.artists;
    if(g.status==='fulfilled'){
      const finished=status.updating&&!g.value.status.updating;
      generated=g.value.playlists;status=g.value.status;homeError='';
      if(finished&&detail?.type==='generated')void fill(detail);
    }else if(!generated.length)homeError=g.reason?.status===503?'':'No se pudieron cargar tus listas. Vuelve a intentarlo en un momento.';
    loaded=true;
    clearTimeout(poll);
    if(status.updating&&get(currentView)==='home')poll=setTimeout(loadHome,4000);
    else if(mobile&&serverDown&&get(currentView)==='home')poll=setTimeout(loadHome,10000);
  }
  // Novedades para ti: while the server is still looking (preparing), ask again every 5 s for up to 5 minutes.
  let releases=[],releasePoll=null,releaseTries=0;
  async function loadReleases(){
    clearTimeout(releasePoll);
    try{
      const r=await calendar();releases=r.items||[];
      if(r.preparing&&++releaseTries<60&&get(currentView)==='home')releasePoll=setTimeout(loadReleases,5000);
    }catch{/* The row simply does not show. */}
  }
  function openRelease(r){
    if(r.upcoming){showToast(`Sale el ${releaseDay(r.date)}`);return;}
    open(releaseEntry(r));
  }
  async function loadAlbums(){
    const [f,n]=await Promise.allSettled([albumList({type:'frequent',size:12}),albumList({type:'newest',size:12})]);
    if(f.status==='fulfilled')frequent=f.value;
    if(n.status==='fulfilled')newest=n.value;
  }
  onMount(()=>{
    const stopView=currentView.subscribe(view=>{if(view==='home'){void loadHome();void loadAlbums();releaseTries=0;void loadReleases();}else{clearTimeout(poll);clearTimeout(releasePoll);}});
    let first=true;
    const stopRoot=homeRoot.subscribe(()=>{if(first){first=false;return;}detail=null;pages=[];phone=null;libraryList=null;});
    return()=>{stopView();stopRoot();clearTimeout(poll);clearTimeout(releasePoll);};
  });

  // A short weekly list is explained with the real counts, never padded.
  function shortfall(d,st){
    const w=st.weekly;
    if(d.type!=='generated'||d.id!=='weekly'||!w||d.loading||!(w.listed<w.proposed))return '';
    return `De ${w.proposed} canciones propuestas esta semana, ${w.listed} tienen una fuente disponible.`;
  }
  async function fill(entry){
    const mine=++token;
    try{
      const data=entry.type==='release'?await releaseRows(entry,()=>detail?.id===entry.id&&detail?.type==='release'):await loaders[entry.type](entry);
      if(mine!==token||detail?.id!==entry.id||detail?.type!==entry.type)return;
      const parts=[count(data.rows.length)];
      if(data.updated&&data.rows.length)parts.push(`Actualizada el ${day(data.updated)}`);
      detail={...detail,...data,description:data.description||entry.description||'',meta:parts.join(' · '),loading:false};
    }catch(e){
      if(mine===token&&detail)detail={...detail,loading:false,rows:detail.rows||[],notice:e.message};
    }
  }
  function open(entry){if(mobile&&['local','mixed'].includes(entry.type)){libraryList={id:entry.id,title:entry.title,kind:entry.type};return;}detail={...entry,rows:[],loading:true,notice:''};pages=[];void fill(entry);}
  async function play(entry){
    try{
      const epoch=await beginPlayRequest();
      const {rows}=await loaders[entry.type](entry);
      if(!rows.length){open(entry);return;}
      const playlist=context(entry);
      const tracks=rows.map(r=>({...r.queue,...(playlist?{_playlist:playlist}:{}),_from:entry.title}));
      if(mobile)playList(tracks,epoch);else playQueue(tracks);
    }catch(e){showToast(e.message,'error');}
  }
  async function act(work,done){
    if(busy)return;busy=true;
    try{const result=await work();if(done)showToast(done(result));await loadHome();}
    catch(e){showToast(e.status===429?'Espera un minuto antes de volver a actualizar.':e.status===409?'Todavia no hay artistas identificados en tus escuchas para crear la lista.':e.message,'error');}
    finally{busy=false;}
  }
  const save=()=>act(()=>api.saveGenerated(detail.id),r=>`Copia guardada en tu biblioteca: ${r.name}`);
  const refresh=()=>act(()=>api.refreshHome(),()=>'Actualizando tus listas. La cola actual no cambia.');
  const activate=()=>act(()=>api.activateWeekly(),()=>'Lista semanal activada. Las primeras canciones pueden tardar unos minutos.');
</script>

{#if libraryList}
  {#key libraryList.id}<LibraryPlaylist id={libraryList.id} title={libraryList.title} kind={libraryList.kind} on:back={()=>libraryList=null} />{/key}
{:else if phone}
  <PhonePlaylist title={phone.row.title} songs={phone.songs} playlistId={phone.row.key.startsWith('playlist:')?phone.row.id:null} offline={true} on:back={()=>phone=null} />
{:else if pages.length}
  {@const top=pages[pages.length-1]}
  <div class="home subpage">
    {#if top.type==='artist'}
      <ArtistPage channelId={top.id} source="youtube_music" on:back={()=>pages=pages.slice(0,-1)} on:album={e=>pages=[...pages,{type:'ytalbum',id:e.detail.browseId}]} />
    {:else}
      <AlbumPage browseId={top.id} source="youtube_music" on:back={()=>pages=pages.slice(0,-1)} />
    {/if}
  </div>
{:else if detail}
  <PlaylistDetail title={detail.title} eyebrow={detail.eyebrow} description={detail.description||''} meta={detail.meta||''}
    covers={detail.covers||[]} variant={detail.variant} label={detail.label||''} rows={detail.rows||[]} context={context(detail)}
    loading={detail.loading} notice={status.updating&&detail.type==='generated'?'Actualizando esta lista…':detail.notice||shortfall(detail,status)}
    busy={busy||(detail.type==='generated'&&status.updating)}
    onSave={detail.type==='generated'?save:null} onRefresh={detail.type==='generated'?refresh:null}
    on:back={()=>detail=null}>
    <div slot="empty">
      {#if detail.type==='generated'&&detail.state==='inactive'}
        <p>Tu lista semanal reune canciones de artistas similares a los que mas escuchas.</p>
        <button class="pill" disabled={busy} on:click={activate}>Activar lista semanal</button>
      {:else if detail.type==='generated'}
        <p>{detail.notice||'Esta lista todavia no tiene canciones disponibles.'}</p>
      {:else if detail.type==='liked'}
        <p>Marca canciones con el corazon y apareceran aqui.</p>
      {:else}
        <p>Esta lista no tiene canciones todavia.</p>
      {/if}
    </div>
  </PlaylistDetail>
{:else}
  <div class="home">
    <h1 class="sr-only">Inicio</h1>
    <p class="greeting">{greeting}</p>

    <section aria-label="Escuchado recientemente">
      <div class="quick">
        {#each [liked,...recent.map(recentEntry).slice(0,7)] as entry (entry.type+entry.id)}
          <div class="quick-card">
            <button class="quick-open" on:click={()=>open(entry)} aria-label={`Abrir ${entry.title}`}>
              <span class="quick-cover"><Cover covers={entry.covers||[]} variant={entry.variant} label={entry.label||''} size={160} /></span>
              <strong>{entry.title}</strong>
            </button>
            <button class="quick-play" on:click={()=>play(entry)} aria-label={`Reproducir ${entry.title}`}><i aria-hidden="true" class="ph-fill ph-play"></i></button>
          </div>
        {/each}
      </div>
      {#if loaded&&!recent.length}<p class="hint">Las playlists que escuches apareceran aqui.</p>{/if}
    </section>

    {#if mobile&&offline}<PhoneDownloads on:collection={e=>phone=e.detail} />{/if}
    <section>
      <header class="shelf-head"><h2>Hecho para ti</h2>
        {#if status.updating}<span class="updating" role="status"><i aria-hidden="true" class="ph ph-arrows-clockwise"></i> Actualizando…</span>{/if}
      </header>
      {#if generated.length}
        <div class="shelf">
          {#each generated.map(generatedEntry) as entry (entry.id)}
            <div class="card">
              <button class="card-open" on:click={()=>open(entry)} aria-label={`Abrir ${entry.title}`}>
                <Cover covers={entry.covers} variant={entry.variant} label={entry.label} />
                <strong>{entry.title}</strong>
                <small>{entry.state==='inactive'?'Activala para recibir canciones cada semana.':entry.count?entry.description:'Todavia sin canciones disponibles.'}</small>
              </button>
              {#if entry.count}<span class="card-overlay"><button class="card-play" on:click={()=>play(entry)} aria-label={`Reproducir ${entry.title}`}><i aria-hidden="true" class="ph-fill ph-play"></i></button></span>{/if}
            </div>
          {/each}
        </div>
      {:else if !loaded||status.updating}
        <div class="shelf" aria-hidden="true">{#each Array(4) as _}<div class="card skeleton"><span class="block"></span><i></i><i></i></div>{/each}</div>
        {#if status.updating}<p class="hint">Preparando tus listas a partir de lo que escuchas. Puede tardar un par de minutos.</p>{/if}
      {:else}
        <p class="hint">{homeError||status.error||(status.profile==='insufficient_profile'
          ?'Escucha musica durante unos dias y aqui apareceran listas hechas para ti.'
          :'Todavia no hay listas para tu perfil. Se prepararan cuando haya artistas reconocidos en tus escuchas.')}</p>
      {/if}
    </section>

    {#if releases.length}
      {#each [[false,'Novedades para ti'],[true,'Proximamente']] as [upcoming,heading]}
        {@const rows=releases.filter(r=>!!r.upcoming===upcoming)}
        {#if rows.length}
          <section>
            <header class="shelf-head"><h2>{heading}</h2></header>
            <div class="shelf">
              {#each rows as r (r.id)}
                <div class="card">
                  <button class="card-open" on:click={()=>openRelease(r)} aria-label={`Abrir ${r.title}`}>
                    <Cover covers={releaseEntry(r).covers} />
                    <strong>{r.title}</strong>
                    <small>{releaseLine(r)}</small>
                  </button>
                </div>
              {/each}
            </div>
          </section>
        {/if}
      {/each}
    {/if}

    {#if artists.length}
      <section>
        <header class="shelf-head"><h2>Artistas similares a los que escuchas</h2></header>
        <div class="shelf">
          {#each artists as artist (artist.channelId)}
            <div class="card">
              <button class="card-open" on:click={()=>pages=[{type:'artist',id:artist.channelId}]} aria-label={`Abrir ${artist.name}`}>
                <Cover covers={artist.thumbnail?[artist.thumbnail]:[]} variant="artist" />
                <strong>{artist.name}</strong>
                <small>Similar a {artist.similarTo}</small>
              </button>
            </div>
          {/each}
        </div>
      </section>
    {/if}

    {#each [['Lo que mas escuchas',frequent],['Añadido recientemente a tu biblioteca',newest]] as [heading,albums]}
      {#if albums.length}
        <section>
          <header class="shelf-head"><h2>{heading}</h2></header>
          <div class="shelf">
            {#each albums.map(albumEntry) as entry (entry.id)}
              <div class="card">
                <button class="card-open" on:click={()=>open(entry)} aria-label={`Abrir ${entry.title}`}>
                  <Cover covers={entry.covers} />
                  <strong>{entry.title}</strong>
                  <small>{entry.description}</small>
                </button>
                <span class="card-overlay"><button class="card-play album" on:click={()=>play(entry)} aria-label={`Reproducir ${entry.title}`}><i aria-hidden="true" class="ph-fill ph-play"></i></button></span>
              </div>
            {/each}
          </div>
        </section>
      {/if}
    {/each}
  </div>
{/if}

<style>
  .home{--gutter:16px;padding:20px var(--gutter) 24px;max-width:1800px}
  .subpage{padding-top:16px}
  .sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
  .greeting{font-size:1.5rem;font-weight:800;letter-spacing:-.01em;margin-bottom:14px}
  section{margin-bottom:28px}
  .hint{color:#b3b3b3;font-size:.9rem;margin-top:10px}

  .quick{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
  .quick-card{position:relative;display:flex;align-items:center;height:56px;border-radius:6px;background:#ffffff14;overflow:hidden;transition:background .15s}
  .quick-card:hover{background:#ffffff26}
  .quick-open{flex:1;min-width:0;height:100%;display:flex;align-items:center;gap:10px;text-align:left}
  .quick-cover{flex:none;width:56px;height:56px}
  .quick-cover :global(.cover){border-radius:0;box-shadow:none}
  .quick-open strong{font-size:.82rem;font-weight:700;line-height:1.2;display:-webkit-box;-webkit-line-clamp:2;line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere}
  .quick-play{flex:none;width:32px;height:32px;min-height:0;margin:0 8px 0 4px;border-radius:50%;background:var(--color-armonia-accent);color:#1a1126;display:grid;place-items:center;font-size:.95rem}

  .shelf-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:12px}
  h2{font-size:1.35rem;font-weight:800;letter-spacing:-.01em;line-height:1.2}
  .updating{flex:none;font-size:.78rem;color:#c4a3ff;display:inline-flex;align-items:center;gap:.3rem}
  .updating i{animation:spin 1.2s linear infinite}
  .shelf{display:grid;grid-auto-flow:column;grid-auto-columns:148px;gap:14px;overflow-x:auto;margin:0 calc(-1 * var(--gutter));padding:0 var(--gutter) 6px;scroll-snap-type:x proximity;scroll-padding-left:var(--gutter);scrollbar-width:none}
  .shelf::-webkit-scrollbar{display:none}
  .card{position:relative;scroll-snap-align:start;min-width:0}
  .card-open{display:flex;flex-direction:column;width:100%;text-align:left;gap:0}
  .card-open strong{margin-top:10px;font-size:.92rem;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .card-open small{margin-top:3px;color:#b3b3b3;font-size:.8rem;line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
  .card-overlay{position:absolute;left:0;right:0;top:0;aspect-ratio:1;pointer-events:none}
  .card-play{position:absolute;right:8px;bottom:8px;pointer-events:auto;width:40px;height:40px;min-height:0;border-radius:50%;background:var(--color-armonia-accent);color:#1a1126;display:grid;place-items:center;font-size:1.15rem;box-shadow:0 6px 14px #0008;transition:transform .12s,opacity .15s}
  .card-play:hover,.quick-play:hover{transform:scale(1.06);background:var(--color-armonia-accentHover)}
  .skeleton .block{display:block;aspect-ratio:1;border-radius:6px;background:#ffffff12}
  .skeleton i{display:block;height:.7rem;border-radius:4px;background:#ffffff12;margin-top:10px;width:80%}
  .skeleton i+i{width:55%;margin-top:7px}
  :global(.pill){margin-top:14px;padding:.75rem 1.6rem;border-radius:999px;background:var(--color-armonia-accent);color:#1a1126;font-weight:700}
  :global(.pill:disabled){opacity:.5}
  @keyframes spin{to{transform:rotate(360deg)}}

  @media(max-width:339px){.quick{grid-template-columns:1fr}}
  /* On a phone a tap opens the album; the direct play button stays on the lists made for the listener. */
  @media(max-width:767px){.card-play.album{display:none}}
  @media(min-width:768px){
    .home{--gutter:32px;padding-top:28px}
    .greeting{font-size:2rem;margin-bottom:18px}
    section{margin-bottom:36px}
    .quick{grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}
    .quick-card{height:64px}
    .quick-cover{width:64px;height:64px}
    .quick-open{gap:14px}
    .quick-open strong{font-size:.95rem}
    .quick-play{width:40px;height:40px;font-size:1.1rem;margin-right:12px}
    h2{font-size:1.5rem}
    .shelf{grid-auto-columns:clamp(170px,15vw,212px);gap:8px;padding-left:calc(var(--gutter) - 12px);scroll-padding-left:calc(var(--gutter) - 12px)}
    .card{padding:12px;border-radius:8px;transition:background .15s}
    .card:hover{background:#ffffff12}
    .card-open strong{font-size:1rem}
    .card-open small{font-size:.85rem}
    .card-overlay{left:12px;right:12px;top:12px}
    .card-play{width:48px;height:48px;font-size:1.35rem}
  }
  @media(min-width:768px) and (hover:hover){
    .quick-play,.card-play{opacity:0}
    .quick-card:hover .quick-play,.quick-play:focus-visible,.card:hover .card-play,.card-play:focus-visible{opacity:1}
  }
</style>
