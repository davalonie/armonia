<script>
  import {pullRefresh} from '../lib/pullRefresh.js';
  import {mobile} from '../lib/native.js';
  import PhoneDownloads from '../components/PhoneDownloads.svelte';
  import PhoneAlbum from '../components/PhoneAlbum.svelte';
  import PhonePlaylist from '../components/PhonePlaylist.svelte';
  import {albumList} from '../lib/albums.js';
  import FastScroll from '../components/FastScroll.svelte';
  import {scrollInitial,scrollMonth} from '../lib/fastScroll.js';
  // Biblioteca, as in the app: «Nueva playlist» and «Importar playlist» on top, then the chips Playlists · Albumes ·
  // Artistas · Canciones (the chosen one is remembered). «Tus favoritos» is the first row of Playlists.
  import {tick} from 'svelte';
  import {libraryArtist} from '../lib/stores/viewStore.js';
  import Playlists from './Playlists.svelte';
  import ExternalFavorites from '../components/ExternalFavorites.svelte';
  import Liked from './Liked.svelte';
  import Library from './Library.svelte';
  import Artists from './Artists.svelte';
  import Cover from '../components/Cover.svelte';
  import PlaylistDetail from '../components/PlaylistDetail.svelte';
  import {coverArtUrl} from '../lib/api.js';
  import {loaders,albumEntry,count} from '../lib/lists.js';
  const TABS=[['playlists','Playlists'],['albums','Albumes'],['artists','Artistas'],['songs','Canciones'],...(mobile?[['offline','En el telefono']]:[])];
  const TAB_KEY='armonia:biblioteca';
  const savedTab=()=>{try{const t=localStorage.getItem(TAB_KEY);return TABS.some(([id])=>id===t)?t:'playlists';}catch{return 'playlists';}};
  let insidePlaylist=false,insideArtist=false,phone=null,phoneAlbum=null;
  let tab=savedTab(),playlistsPane,albums=null,error='',albumFilter='',albumSort='name',detail=null,token=0;
  $: if ($libraryArtist) {tab='artists';phone=null;phoneAlbum=null;detail=null;}
  async function loadAlbums(){
    if(albums)return;
    error='';
    try{albums=await albumList({type:'alphabeticalByName',size:500});}catch(e){error=e.message;}
  }
  async function openAlbum(a){
    if(mobile){phoneAlbum=a;return;}
    const mine=++token,entry=albumEntry(a);
    detail={entry,rows:[],loading:true,notice:''};
    try{const data=await loaders.album(entry);if(mine===token)detail={...detail,rows:data.rows,loading:false,meta:count(data.rows.length)};}
    catch(e){if(mine===token)detail={...detail,loading:false,notice:e.message};}
  }
  const fold=s=>(s||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
  $: shownAlbums=(albums||[]).filter(a=>!albumFilter||fold(a.name+' '+a.artist).includes(fold(albumFilter)))
    .sort((a,b)=>albumSort==='artist'?(a.artist||'').localeCompare(b.artist||'','es')||a.name.localeCompare(b.name,'es')
      :albumSort==='recent'&&mobile?(b.year||0)-(a.year||0)||a.name.localeCompare(b.name,'es'):albumSort==='recent'?String(b.created||'').localeCompare(String(a.created||'')):a.name.localeCompare(b.name,'es'));
  let albumGrid;
  $: albumLabels=albumSort==='recent'?shownAlbums.map(a=>scrollMonth(a.created)):shownAlbums.map(a=>scrollInitial(albumSort==='artist'?a.artist:a.name));
  function select(id){tab=id;detail=null;insideArtist=false;if(id==='albums')void loadAlbums();if(id!=='liked')try{localStorage.setItem(TAB_KEY,id);}catch{}}
  if(tab==='albums')void loadAlbums();
  // The two actions live in the Playlists pane (its dialogs); open it first when another chip is chosen.
  async function playlistAction(name){if(tab!=='playlists'){select('playlists');await tick();}playlistsPane?.[name]();}
</script>

{#if phone}
  <PhonePlaylist title={phone.row.title} songs={phone.songs} playlistId={phone.row.key.startsWith('playlist:')?phone.row.id:null} offline={true} on:back={()=>phone=null} />
{:else if phoneAlbum}
  {#key phoneAlbum.id}<PhoneAlbum id={phoneAlbum.id} title={phoneAlbum.name} on:back={()=>phoneAlbum=null}/>{/key}
{:else if detail}
  <PlaylistDetail title={detail.entry.title} eyebrow="Album" description={detail.entry.description||''} meta={detail.meta||''}
    covers={detail.entry.covers} variant="plain" rows={detail.rows} loading={detail.loading} notice={detail.notice}
    on:back={()=>{token++;detail=null;}}><div slot="empty"><p>Este album no tiene canciones disponibles.</p></div></PlaylistDetail>
{:else}
<section class="collection" hidden={mobile && (insidePlaylist && tab==='playlists' || insideArtist && tab==='artists' || tab==='liked')}>
  <div class="heading"><h1>Biblioteca</h1></div>
  {#if tab==='liked'}
    <button class="back" on:click={()=>select(savedTab())}><i aria-hidden="true" class="ph ph-arrow-left"></i> Biblioteca</button>
  {:else}
    <div class="actions">
      <button class="assist" on:click={()=>playlistAction('openCreate')}><i aria-hidden="true" class="ph ph-plus"></i> Nueva playlist</button>
      <button class="assist" on:click={()=>playlistAction('openImport')}><i aria-hidden="true" class="ph ph-download-simple"></i> Importar playlist</button>
    </div>
    <nav class="chips" aria-label="Contenido de la biblioteca">{#each TABS as [id,label]}
      <button class="chip" class:on={tab===id} aria-pressed={tab===id} on:click={()=>select(id)}>{label}</button>
    {/each}</nav>
  {/if}
</section>
{#if tab==='playlists'}<div class="pane"><Playlists bind:this={playlistsPane} on:detail={e=>insidePlaylist=e.detail} on:favorites={()=>select('liked')} /></div>
{:else if tab==='offline'}<PhoneDownloads embedded on:collection={e=>phone=e.detail} />
{:else if tab==='liked'}<Liked on:back={()=>select('playlists')}/><ExternalFavorites />
{:else if tab==='artists'}<Artists on:detail={e=>insideArtist=e.detail}/>
{:else if tab==='songs'}<Library />
{:else}
  <section use:pullRefresh={()=>{albums=null;return loadAlbums();}} class="collection body">
    <div class="toolbar">
      <label class="filter"><i aria-hidden="true" class="ph ph-magnifying-glass"></i>
        <input type="search" bind:value={albumFilter} aria-label="Buscar en tus albumes" placeholder="Buscar en tus albumes"></label>
      {#if mobile}
        <div class="phone-chips" role="group" aria-label="Ordenar albumes">{#each [['name','Nombre'],['artist','Artista'],['recent','Mas recientes']] as [id,label]}<button aria-pressed={albumSort===id} on:click={()=>albumSort=id}>{label}</button>{/each}</div>
        {#if albums && shownAlbums.length}<small class="total">{shownAlbums.length} {shownAlbums.length===1?'album':'albumes'}</small>{/if}
      {:else}<label class="sort"><i aria-hidden="true" class="ph ph-arrows-down-up"></i>
        <select bind:value={albumSort} aria-label="Ordenar albumes"><option value="name">Nombre</option><option value="artist">Artista</option><option value="recent">Añadidos recientemente</option></select></label>{/if}
    </div>
    {#if error}<p class="none" role="alert">{error} <button class="retry" on:click={()=>{albums=null;void loadAlbums();}}>Reintentar</button></p>
    {:else if !albums}<p class="none" role="status">Cargando albumes…</p>
    {:else if !shownAlbums.length}<p class="none">{albumFilter?`Ningun album coincide con «${albumFilter}».`:'Todavia no hay albumes en tu biblioteca.'}</p>
    {:else}
      <FastScroll labels={albumLabels} list={albumGrid} />
      <div class="grid" bind:this={albumGrid}>{#each shownAlbums as a (a.id)}
        <button class="album" aria-label={`Abrir ${a.name}`} on:click={()=>openAlbum(a)}>
          <Cover variant={mobile?"album":"plain"} covers={a.coverArt?[coverArtUrl(a.coverArt,300)]:[]} size={300} /><b>{a.name}</b><small>{a.artist}</small></button>
      {/each}</div>
    {/if}
  </section>
{/if}
{/if}

<style>
  .collection{width:100%;max-width:1100px;margin:0 auto;padding:16px 16px 0}
  .collection.body{padding-bottom:32px}
  @media(min-width:768px){.collection{padding:28px 32px 0}}
  h1{font-size:1.9rem;font-weight:800;margin:4px 0 12px}
  .heading{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}
  .actions{display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap}
  .assist{display:flex;align-items:center;gap:6px;padding:7px 14px;border:1px solid #ffffff35;border-radius:9px;font-size:.9rem;font-weight:500}
  .assist:hover{background:#ffffff0d}
  .back{display:flex;align-items:center;gap:6px;padding:6px 0;color:var(--color-armonia-muted);font-weight:600}
  .back:hover{color:#fff}
  .chips{display:flex;gap:8px;overflow-x:auto;padding-bottom:6px;scrollbar-width:none}
  .chip{flex-shrink:0;padding:8px 16px;border-radius:999px;background:#ffffff14;font-size:.9rem;font-weight:500}
  .chip.on{background:var(--color-armonia-accent);color:#121015;font-weight:700}
  .pane :global(> div){padding-top:12px}
  .toolbar{display:flex;gap:10px;align-items:center;margin:12px 0 14px;flex-wrap:wrap}
  .filter{flex:1;min-width:180px;display:flex;align-items:center;gap:8px;background:#ffffff14;border-radius:8px;padding:0 12px;height:42px;color:var(--color-armonia-muted)}
  .filter input{flex:1;min-width:0;background:transparent;border:0;outline:0;color:var(--color-armonia-text);font-size:.95rem}
  .filter:focus-within{outline:2px solid var(--color-armonia-accent)}
  .sort{display:inline-flex;align-items:center;gap:6px;font-size:.9rem;font-weight:600}
  .sort select{background:transparent;border:0;color:inherit;font:inherit;padding:6px 2px}
  .sort option{background:#1f1c26}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:18px 14px}
  @media(min-width:768px){.grid{grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:24px 20px}}
  .album{display:flex;flex-direction:column;gap:6px;text-align:left;padding:6px;border-radius:10px}
  .album:hover,.album:focus-visible{background:#ffffff0d}
  .album b{font-weight:600;font-size:.95rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .album small{color:var(--color-armonia-muted);font-size:.82rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .none{color:var(--color-armonia-muted);padding:32px 8px;text-align:center}
  .retry{text-decoration:underline;margin-left:6px}
</style>
