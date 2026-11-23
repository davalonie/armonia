<script>
  // Ajustes y cuenta, in the same order as the app: Reproduccion, Servidor, Buscar, Biblioteca, Cuenta. The phone-only
  // sections of the app (cache, data saving, music on the phone, Android Auto) have nothing to set in a browser.
  import {onMount} from 'svelte';
  import {getSession,setSession,logout,rescan as requestRescan,library as libApi,getStats} from '../lib/api.js';
  import {api} from '../lib/homelab.js';
  import {closePlayer,continueSimilar,saveContinueSimilar} from '../lib/stores/playerStore.js';
  import {SEARCH_SOURCE_KEY,searchSource as readSource} from '../lib/searchSource.js';
  import {APP_NAME} from '../lib/brand.js';
  const session=getSession();
  let source=readSource();
  function setSource(s){source=s;localStorage.setItem(SEARCH_SOURCE_KEY,s);}

  let savingSimilar=false,similarError='';
  async function toggleSimilar(){
    if(savingSimilar)return;savingSimilar=true;similarError='';
    try{await saveContinueSimilar(!$continueSimilar);}
    catch{similarError='No se pudo guardar el ajuste. Se mantiene como estaba.';}
    finally{savingSimilar=false;}
  }

  let serverStatus='loading',serverVersion='',stats=null,statsError='',statsLoading=true;
  async function checkStatus(){serverStatus='loading';try{serverVersion=(await libApi('ping')).serverVersion||'?';serverStatus='ok';}catch{serverStatus='error';}}
  async function loadStats(){statsLoading=true;statsError='';try{stats=await getStats();}catch(e){statsError=e.message;}finally{statsLoading=false;}}
  const refreshAll=()=>Promise.all([checkStatus(),loadStats()]);

  let rescanMsg='',rescanOk=false,rescanLoading=false;
  async function rescan(){
    rescanLoading=true;rescanMsg='';
    try{await requestRescan();rescanMsg='Biblioteca escaneada.';rescanOk=true;}
    catch{rescanMsg='No se pudo escanear la biblioteca.';rescanOk=false;}
    finally{rescanLoading=false;}
  }

  // Recomendaciones (Aurral): a status line when linked, the form only when not (moved here from «Mas»).
  let linked=null,linkError=false,linking=false,aurralUser='',aurralPassword='';
  async function refreshLink(){linkError=false;try{linked=(await api.aurralStatus()).linked;}catch{linked=null;linkError=true;}}
  async function link(){
    if(linking)return;linking=true;linkError=false;
    try{await api.link(aurralUser,aurralPassword);linked=true;}
    catch{linkError=true;}
    finally{aurralPassword='';linking=false;}
  }

  let logoutError='';
  async function doLogout(){
    if(!confirm(`¿Cerrar sesion? Tendras que volver a iniciar sesion para usar ${APP_NAME}.`))return;
    closePlayer();logoutError='';
    try{await logout();setSession(null);location.reload();}
    catch{logoutError='No se pudo cerrar la sesion en el servidor. Reintenta cuando vuelva la conexion.';}
  }

  function bar(label,used,total){const pct=total>0?used/total*100:0;return {label,used,total,pct,warn:pct>85};}
  function fmtBytes(bytes){
    if(!bytes)return '0 B';
    const units=['B','KB','MB','GB','TB'];let i=0,v=bytes;
    while(v>=1024&&i<units.length-1){v/=1024;i++;}
    return `${v.toFixed(i>1?1:0).replace('.',',')} ${units[i]}`;
  }
  $: bars=stats?[bar('Disco',stats.disk.used,stats.disk.total),bar('RAM',stats.ram.used,stats.ram.total)]:[];
  onMount(()=>{void refreshAll();void refreshLink();});
</script>

<section class="settings">
  <header>
    <img src="/armonia.svg" alt="" class="logo" draggable="false">
    <h1>Ajustes</h1>
    <button class="icon" aria-label="Actualizar" title="Actualizar" on:click={refreshAll}><i aria-hidden="true" class="ph ph-arrows-clockwise"></i></button>
  </header>

  <h2>Reproduccion</h2>
  <div class="card">
    <button class="row" role="switch" aria-checked={$continueSimilar} disabled={savingSimilar} on:click={toggleSimilar}>
      <span><b>Continuar con musica similar</b>
        <small>{$continueSimilar?'Cuando termina lo que has elegido, siguen sonando canciones relacionadas.':'Desactivado: la reproduccion se detiene al terminar la cola.'}</small>
        {#if similarError}<small class="error" role="alert">{similarError}</small>{/if}</span>
      <span class="switch" class:on={$continueSimilar} aria-hidden="true"><span></span></span>
    </button>
  </div>

  <h2>Servidor</h2>
  <div class="card pad">
    <p class="status"><span class="dot" class:ok={serverStatus==='ok'} class:bad={serverStatus==='error'}></span>
      <span><b>Navidrome</b><small>{serverStatus==='loading'?'Comprobando…':serverStatus==='ok'?`Conectado · v${serverVersion}`:'Sin conexion'}</small></span></p>
    {#if statsLoading}<p class="muted" role="status">Cargando…</p>
    {:else if statsError}<p class="error" role="alert">No se pudieron leer los datos del servidor: {statsError}</p>
    {:else if stats}
      {#each bars as b}
        <div class="meter"><p><span>{b.label}</span><span>{fmtBytes(b.used)} de {fmtBytes(b.total)}</span></p>
          <div class="track"><div class:warn={b.warn} style:width="{b.pct.toFixed(1)}%"></div></div></div>
      {/each}
      <div class="meter"><p><span>CPU</span><span>{stats.cpu_percent.toFixed(1).replace('.',',')} %</span></p>
        <div class="track"><div class:warn={stats.cpu_percent>80} style:width="{Math.min(stats.cpu_percent,100).toFixed(1)}%"></div></div></div>
    {/if}
  </div>

  <h2>Buscar</h2>
  <div class="card pad">
    <p class="muted">Donde buscar y de donde descargar musica.</p>
    <div class="segmented" role="radiogroup" aria-label="Fuente de busqueda">
      {#each [['youtube_music','YouTube Music'],['youtube','YouTube']] as [value,label]}
        <button role="radio" aria-checked={source===value} class:on={source===value} on:click={()=>setSource(value)}>{label}</button>
      {/each}
    </div>
  </div>

  <h2>Biblioteca</h2>
  <div class="card pad">
    <p class="muted">Lanza un escaneo de la biblioteca de Navidrome para incorporar las canciones recien descargadas.</p>
    <button class="primary" disabled={rescanLoading} on:click={rescan}>{#if rescanLoading}<i aria-hidden="true" class="ph ph-circle-notch spin"></i>{/if} Escanear biblioteca</button>
    {#if rescanMsg}<p class:ok={rescanOk} class:error={!rescanOk} role="status">{rescanMsg}</p>{/if}
  </div>

  <h2>Cuenta</h2>
  <div class="card pad">
    <p class="status"><i aria-hidden="true" class="ph-fill ph-user-circle user"></i><span><b>{session?.username??'—'}</b><small>Cuenta de Navidrome</small></span></p>
    {#if linked===true}<p>Recomendaciones: vinculadas</p>
    {:else if linked===false}
      <form on:submit|preventDefault={link}>
        <p class="muted">Vincula tu cuenta de Aurral para recibir recomendaciones.</p>
        <label>Usuario Aurral<input bind:value={aurralUser} autocomplete="username" required></label>
        <label>Contraseña Aurral<input type="password" bind:value={aurralPassword} autocomplete="current-password" required></label>
        <button class="primary" disabled={linking||!aurralUser.trim()||!aurralPassword}>Vincular</button>
        {#if linkError}<p class="error" role="alert">No se pudo vincular la cuenta</p>{/if}
      </form>
    {:else if linkError}<button class="link" on:click={refreshLink}>Reintentar consulta de recomendaciones</button>
    {:else}<p class="muted" role="status">Consultando recomendaciones…</p>{/if}
    <button class="danger" on:click={doLogout}>Cerrar sesion</button>
    {#if logoutError}<p class="error" role="alert">{logoutError}</p>{/if}
  </div>

  <footer>
    <img src="/armonia.svg" alt="" draggable="false">
    <b>{APP_NAME}</b>
  </footer>
</section>

<style>
  .settings{max-width:760px;margin:0 auto;padding:1.25rem 1rem 8rem}
  header{display:flex;align-items:center;gap:.5rem;margin-bottom:.5rem}
  .logo{width:40px;height:40px;border-radius:10px}
  h1{font-size:2rem;font-weight:800;color:#fff;flex:1}
  h2{margin:1.5rem 0 .5rem .25rem;font-size:.78rem;letter-spacing:.08em;text-transform:uppercase;font-weight:700;color:var(--color-armonia-muted)}
  .card{background:#ffffff0a;border-radius:14px;overflow:hidden}
  .card.pad{padding:1rem;display:grid;gap:.85rem}
  .row{display:flex;align-items:center;gap:.9rem;width:100%;padding:1rem;text-align:left}
  .row>span:first-child,.status>span:not(.dot){flex:1;min-width:0;display:flex;flex-direction:column;gap:.15rem}
  b{font-weight:600;color:#fff}
  small,.muted{color:var(--color-armonia-muted);font-size:.85rem;line-height:1.35}
  .error{color:#ffb4a8;font-size:.85rem}
  .ok{color:#9be7c4;font-size:.85rem}
  .icon{width:44px;height:44px;display:grid;place-items:center;border-radius:50%;font-size:1.3rem;color:var(--color-armonia-muted)}
  .icon:hover{background:#ffffff14;color:#fff}
  .switch{flex:none;width:46px;height:28px;border-radius:99px;background:#ffffff26;padding:3px;transition:background .15s}
  .switch span{display:block;width:22px;height:22px;border-radius:50%;background:#fff;transition:transform .15s}
  .switch.on{background:var(--color-armonia-accent)}
  .switch.on span{transform:translateX(18px)}
  .status{display:flex;align-items:center;gap:.75rem}
  .dot{width:10px;height:10px;border-radius:50%;background:#ffffff40;flex:none}
  .dot.ok{background:#2ec4b6}.dot.bad{background:#ff6b6b}
  .user{font-size:2.2rem;color:var(--color-armonia-accent)}
  .meter p{display:flex;justify-content:space-between;font-size:.88rem;margin-bottom:.35rem}
  .track{height:8px;border-radius:99px;background:#ffffff1a;overflow:hidden}
  .track div{height:100%;border-radius:99px;background:var(--color-armonia-accent)}
  .track div.warn{background:#ff8a80}
  .segmented{display:flex;background:#00000033;border-radius:99px;padding:3px}
  .segmented button{flex:1;padding:.55rem;border-radius:99px;font-size:.9rem;font-weight:600;color:var(--color-armonia-muted)}
  .segmented button.on{background:var(--color-armonia-accent);color:#16121d}
  .primary{display:flex;align-items:center;justify-content:center;gap:.5rem;padding:.7rem 1rem;border-radius:99px;background:var(--color-armonia-accent);color:#16121d;font-weight:700}
  .primary:disabled{opacity:.5}
  .danger{padding:.7rem 1rem;border-radius:99px;border:1px solid #ff8a8066;color:#ffb4a8;font-weight:600}
  .link{text-decoration:underline;text-align:left}
  form{display:grid;gap:.6rem}
  label{display:grid;gap:.3rem;font-size:.85rem;color:var(--color-armonia-muted)}
  input{background:#ffffff12;border-radius:8px;padding:.6rem .75rem;color:#fff}
  .spin{animation:spin 1s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}
  footer{display:flex;flex-direction:column;align-items:center;gap:.25rem;margin-top:2rem;text-align:center}
  footer img{width:56px;height:56px;border-radius:14px;margin-bottom:.35rem}
  footer a{text-decoration:underline}
</style>
