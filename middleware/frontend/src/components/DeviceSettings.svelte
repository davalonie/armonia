<script>
  import {onMount} from 'svelte';
  import {mobile} from '../lib/native.js';
  import {currentView} from '../lib/stores/viewStore.js';
  import {APP_NAME} from '../lib/brand.js';

  export let fmtBytes;
  let state, busy=false, error='', request=0;
  async function load(){
    if ($currentView!=='settings' || document.hidden) return;
    const id=++request;
    try{const result=await mobile.deviceSettings();if(id===request){state=result;error='';}}
    catch{if(id===request)error='No se pudieron leer los ajustes del teléfono.';}
  }
  async function change(setting,value){
    if(busy)return;
    busy=true;
    try{await mobile.changeDeviceSetting({setting,value});await load();}
    catch{error='No se pudo aplicar el cambio.';}
    finally{busy=false;}
  }
  onMount(()=>{
    const stop=currentView.subscribe(view=>{if(view==='settings')void load();});
    document.addEventListener('visibilitychange',load);
    return ()=>{stop();document.removeEventListener('visibilitychange',load);};
  });
  const dateFormat=new Intl.DateTimeFormat('es',{weekday:'short',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});
</script>

{#if error}<p class="error" role="alert">{error} <button on:click={load}>Reintentar</button></p>{/if}
{#if state}
  <h2>Cache de reproduccion</h2>
  <div class="card pad">
    <p class="muted">Las canciones que escuchas se guardan en este telefono, asi que volver a escucharlas no gasta datos.</p>
    <p>Usando {fmtBytes(state.cacheBytes)} de {state.cacheMb/1024} GB</p>
    <div class="segmented" role="group" aria-label="Limite de cache">
      {#each [1,2,4,8] as gb}<button aria-pressed={state.cacheMb===gb*1024} class:on={state.cacheMb===gb*1024} disabled={busy} on:click={()=>change('cacheMb',gb*1024)}>{gb} GB</button>{/each}
    </div>
    <p class="muted">El nuevo limite se aplica la proxima vez que abras la aplicacion.</p>
    <button class="device-switch" role="switch" aria-checked={state.wifi} disabled={busy} on:click={()=>change('wifi',!state.wifi)}>
      <span>Guardar con Wi‑Fi lo que mas escuchas<small>Con Wi‑Fi, la semanal, tus favoritas y las mas escuchadas se guardan en el telefono. Usa como mucho el 40 % de la cache.</small></span>
      <span class="switch" class:on={state.wifi} aria-hidden="true"><span></span></span>
    </button>
    <button class="outline" disabled={busy} on:click={()=>change('clearCache')}>Vaciar cache</button>
    <p class="muted">Musica sin conexion (albumes y playlists que has guardado): {state.offlineCount} guardadas, {fmtBytes(state.offlineBytes)}. Las descargas solo se hacen con Wi‑Fi.</p>
    <button class="outline" disabled={busy||!state.offlineCount} on:click={()=>change('removeOffline')}>Quitar toda la musica sin conexion</button>
  </div>
  <h2>Ahorro de datos</h2>
  <div class="card pad">
    <div class="segmented" role="group" aria-label="Ahorro de datos">
      {#each [['no','No'],['datos','Con datos'],['siempre','Siempre']] as [v,label]}<button class:on={state.saver===v} aria-pressed={state.saver===v} disabled={busy} on:click={()=>change('saver',v)}>{label}</button>{/each}
    </div>
    <p class="muted">Las canciones llegan a 64 kbps, la mitad de datos. Con mala conexion se usa siempre. Lo que ya esta en el telefono suena desde ahi, sin gastar nada.</p>
    {#if state.mobileBytes!=null}<p>Este mes Armonia ha gastado {fmtBytes(state.mobileBytes)} de datos moviles y {fmtBytes(state.wifiBytes)} de Wi‑Fi.</p>{/if}
  </div>
  <h2>Android Auto</h2>
  <div class="card pad">
    <p class="muted">Android Auto solo muestra {APP_NAME} mientras «Fuentes desconocidas» este activado en sus ajustes de desarrollador.</p>
    <p>{state.restricted?'El uso en segundo plano de '+APP_NAME+' esta restringido.':state.optimized?'La optimizacion de bateria esta activada y Android puede detener '+APP_NAME+' en segundo plano.':'Bateria: sin restricciones'}</p>
    {#if state.restricted||state.optimized}<button class="outline" on:click={()=>change('appSettings')}>Abrir los ajustes de {APP_NAME}</button>{/if}
    <b>Conexiones recientes</b>
    {#each state.connections as c}<small>{dateFormat.format(c.at)} · {c.name} {c.event}</small>{:else}<small>Todavia ninguna.</small>{/each}
  </div>
{/if}
