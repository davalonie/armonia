<script>
  // «Más», as in the app: your activity and your account. Downloads only show up here when one has failed.
  import {onMount} from 'svelte';
  import {currentView,showView} from '../lib/stores/viewStore.js';
  import {getSession,listDownloads} from '../lib/api.js';
  import {loadManualInbox} from '../lib/manualInbox.js';
  const account=getSession()?.username||'';
  let failures=0,pending=0;
  async function refresh(){
    const [jobs,inbox]=await Promise.allSettled([listDownloads(),loadManualInbox()]);
    // Cancelled by the user does not count: only what went wrong and can be retried.
    if(jobs.status==='fulfilled')failures=(jobs.value.downloads||[]).filter(d=>d.status==='error'||d.status==='timeout').length;
    if(inbox.status==='fulfilled')pending=(inbox.value.items||[]).filter(i=>i.status!=='saved').length;
  }
  onMount(()=>currentView.subscribe(view=>{if(view==='more')void refresh();}));
</script>

<section class="more">
  <header><h1>Más</h1>{#if account}<p><i aria-hidden="true" class="ph ph-user-circle"></i> {account}</p>{/if}</header>

  <h2>Tu actividad</h2>
  <div class="group">
    <button class="item" on:click={()=>showView('listening')}>
      <i aria-hidden="true" class="ph ph-chart-bar lead"></i>
      <span><b>Historial y estadísticas</b><small>Lo que has escuchado, tus artistas y canciones principales</small></span>
      <i aria-hidden="true" class="ph ph-caret-right go"></i>
    </button>
    <button class="item" on:click={()=>showView('manual-inbox')}>
      <i aria-hidden="true" class="ph ph-plus lead"></i>
      <span><b>Pendientes de añadir</b><small>{pending?`${pending} ${pending===1?'canción espera':'canciones esperan'} a que la añadas a mano`:'Canciones de tus importaciones que no se encontraron'}</small></span>
      <i aria-hidden="true" class="ph ph-caret-right go"></i>
    </button>
    {#if failures}
      <button class="item" on:click={()=>showView('jobs')}>
        <i aria-hidden="true" class="ph ph-download-simple lead warn"></i>
        <span><b>{failures===1?'1 descarga ha fallado':`${failures} descargas han fallado`}</b><small>Ábrelas para volver a intentarlo</small></span>
        <i aria-hidden="true" class="ph ph-caret-right go"></i>
      </button>
    {/if}
  </div>

  <h2>Cuenta y ajustes</h2>
  <div class="group">
    <button class="item" on:click={()=>showView('settings')}>
      <i aria-hidden="true" class="ph ph-gear lead"></i>
      <span><b>Ajustes y cuenta</b><small>Reproducción, servidor, búsqueda, recomendaciones y sesión</small></span>
      <i aria-hidden="true" class="ph ph-caret-right go"></i>
    </button>
  </div>
</section>

<style>
  .more{max-width:760px;margin:0 auto;padding:1.25rem 1rem 7rem}
  header{display:flex;align-items:baseline;justify-content:space-between;gap:1rem;margin-bottom:.5rem}
  h1{font-size:2rem;font-weight:800;color:#fff}
  header p{color:var(--color-armonia-muted);font-size:.9rem;display:flex;align-items:center;gap:.35rem}
  h2{margin:1.5rem 0 .5rem .25rem;font-size:.78rem;letter-spacing:.08em;text-transform:uppercase;font-weight:700;color:var(--color-armonia-muted)}
  .group{background:#ffffff0a;border-radius:14px;overflow:hidden}
  .item{display:flex;align-items:center;gap:.9rem;width:100%;padding:.9rem 1rem;text-align:left;cursor:pointer;min-height:64px}
  .item:hover{background:#ffffff0c}
  .group>*+*{border-top:1px solid #ffffff0f}
  .lead{font-size:1.45rem;color:var(--color-armonia-accent);flex:none}
  .lead.warn{color:#ffb4a8}
  .item>span{flex:1;min-width:0;display:flex;flex-direction:column;gap:.15rem}
  b{font-weight:600;color:#fff}
  small{color:var(--color-armonia-muted);font-size:.82rem;line-height:1.3}
  .go{color:var(--color-armonia-muted);flex:none}
</style>
