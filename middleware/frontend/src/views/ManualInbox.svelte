<script>
  import {mobile,mobileImport} from '../lib/native.js';
  import {onMount} from 'svelte';
  import {getSession} from '../lib/api.js';
  import {currentView,showView} from '../lib/stores/viewStore.js';
  import {loadManualInbox,uploadManualAudio,refreshManualPending,deleteManualPending,validateManualAudio,manualInboxError,pendingAudioLabel} from '../lib/manualInbox.js';

  let items=[], loading=false, busy=null, error='', notice='', files={}, fileErrors={}, rowErrors={}, query='';
  let generation=0, alive=true, controller=null, loadController=null;
  const fold=value=>(value||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
  $: shown=items.filter(item=>fold(`${item.track.title} ${item.track.artist} ${item.originName}`).includes(fold(query)));

  async function load() {
    if (busy) return;
    const epoch=++generation, session=getSession();
    loadController?.abort();
    const request=new AbortController();loadController=request;
    const timer=setTimeout(()=>request.abort(),30000);
    loading=true;error='';
    try {
      const result=await loadManualInbox({signal:request.signal});
      if(alive&&epoch===generation&&getSession()===session) items=result.items||[];
    } catch(e) {if(alive&&epoch===generation&&getSession()===session)error=e.name==='AbortError'?'No se pudo cargar la bandeja a tiempo. Actualiza para reintentarlo.':manualInboxError(e);}
    finally {clearTimeout(timer);if(loadController===request)loadController=null;if(alive&&epoch===generation)loading=false;}
  }
  onMount(()=>{
    alive=true;
    const unsubscribe=currentView.subscribe(view=>{if(view==='manual-inbox')void load();});
    return ()=>{alive=false;generation++;controller?.abort();loadController?.abort();unsubscribe();};
  });
  function pick(item,event) {
    const file=event.target.files?.[0];event.target.value='';
    if(!file)return;
    try{validateManualAudio(file);files={...files,[item.id]:file};fileErrors={...fileErrors,[item.id]:''};}
    catch(e){files={...files,[item.id]:null};fileErrors={...fileErrors,[item.id]:e.message};}
  }
  async function act(item,action) {
    if(busy)return;
    if(action==='delete'&&!confirm(`¿Quitar «${item.track.title}» de Pendientes de añadir? Los archivos que ya hayas guardado en la biblioteca se conservan.`))return;
    const session=getSession();generation++;loadController?.abort();busy=item.id;error='';notice='';rowErrors={...rowErrors,[item.id]:''};
    controller=new AbortController();
    const timer=setTimeout(()=>controller?.abort(),360000);
    try {
      const opts={signal:controller.signal};
      if(action==='upload'&&mobile){
        const result=await mobileImport.pickManualAudio({id:item.id,revision:item.revision});
        if(result.cancelled)return;
      }else if(action==='upload')await uploadManualAudio(item,files[item.id],opts);
      else if(action==='refresh')await refreshManualPending(item,opts);
      else await deleteManualPending(item,opts);
      if(!alive||getSession()!==session)return;
      files={...files,[item.id]:null};
      notice=action==='delete'?'Pendiente eliminado. Tu biblioteca se conserva.':action==='upload'?'Archivo guardado. La bandeja muestra si ya esta disponible en la biblioteca.':'Estado actualizado.';
    } catch(e) {
      if(alive&&getSession()===session)rowErrors={...rowErrors,[item.id]:mobile&&action==='upload'?e.message:manualInboxError(e)};
    } finally {
      clearTimeout(timer);controller=null;busy=null;
      if(alive&&getSession()===session)await load();
    }
  }
</script>

<section class="inbox music-page">
  <button class="back" data-phone-back on:click={()=>showView('library')}>← Biblioteca</button>
  <div class="heading"><h1>Pendientes de añadir</h1>{#if !mobile}<button disabled={loading||!!busy} on:click={load}>Actualizar</button>{/if}</div>
  <p class="intro">Aqui guardas las canciones que has omitido al importar. Puedes terminar tus playlists y recuperar estas canciones mas adelante.</p>
  <p class="intro">Aporta un MP3 que tengas permiso para guardar. Se añadira a tu biblioteca; despues puedes incluirlo en cualquier playlist desde Biblioteca.</p>
  <p class="intro">Se guardara una copia MP3 a 192 kb/s; el archivo original de tu dispositivo se conserva.</p>
  {#if mobile}<small>MP3 de hasta 64 MiB.</small><button class="refresh" disabled={loading||!!busy} on:click={load}>Actualizar</button>{/if}
  {#if !mobile || items.length}<label class="filter">Buscar pendientes<input type="search" bind:value={query} placeholder="Cancion, artista o playlist" /></label>{/if}
  {#if error}<p role="alert">{error}</p>{/if}
  {#if notice}<p role="status">{notice}</p>{/if}
  {#if loading && !items.length}<p role="status">Cargando pendientes…</p>
  {:else if !items.length && !error}<p class="empty">No tienes canciones pendientes. {#if !mobile}«Ninguna coincide» las guarda aqui para que puedas continuar con la importacion.{/if}</p>
  {:else if !shown.length}<p class="empty">No hay pendientes que coincidan con tu busqueda.</p>
  {:else}
    <div class="entries">{#each shown as item (item.id)}
      <article class="entry" data-pending-id={item.id} aria-labelledby={`pending-${item.id}`}>
        <div class="entry-heading"><span class="art" aria-hidden="true">♫</span><div><h2 id={`pending-${item.id}`}>{item.track.title}</h2><p>{item.track.artist}</p><small>De {item.originName}{item.originIndex!=null?` · posicion ${item.originIndex+1}`:''}</small></div></div>
        <p class="state">{pendingAudioLabel(item)}</p>
        {#if rowErrors[item.id]}<p role="alert">{rowErrors[item.id]}</p>{/if}
        {#if item.status==='saved'}
          {#if !item.songId}<p>El archivo ya esta guardado. Puedes volver a consultar su indexacion sin subirlo de nuevo.</p><button disabled={!!busy} on:click={()=>act(item,'refresh')}>Comprobar biblioteca</button>
          {:else}<button class="primary" on:click={()=>showView('library')}>Ir a Biblioteca</button>{/if}
        {:else}
          {#if mobile}<button class="primary" disabled={!!busy} on:click={()=>act(item,'upload')}>Elegir MP3</button>
          {:else}<label class="file">Elegir MP3 para {item.track.title}<input type="file" accept=".mp3,audio/mpeg" disabled={!!busy} on:change={event=>pick(item,event)} /></label>
          {#if files[item.id]}<p class="filename">{files[item.id].name} · {(files[item.id].size/1024/1024).toFixed(1)} MiB</p>{/if}
          {#if fileErrors[item.id]}<p role="alert">{fileErrors[item.id]}</p>{/if}
          <button class="primary" disabled={!!busy||!files[item.id]} on:click={()=>act(item,'upload')}>Guardar MP3 en biblioteca</button>{/if}
        {/if}
        <button class="remove" disabled={!!busy} on:click={()=>act(item,'delete')}>Quitar de pendientes</button>
        {#if busy===item.id}<p role="status">Guardando cambios…</p>{/if}
      </article>
    {/each}</div>
  {/if}
</section>

<style>
  .inbox{max-width:1000px;margin:0 auto;padding:20px 16px 40px}.back{margin-bottom:14px;color:var(--color-armonia-muted)}.heading{display:flex;align-items:center;gap:12px;justify-content:space-between;flex-wrap:wrap}h1{font-size:1.8rem;font-weight:750}.intro{color:var(--color-armonia-muted);margin:10px 0;max-width:75ch}.filter{display:flex;flex-direction:column;gap:6px;margin:20px 0 16px;font-size:.9rem}.filter input{background:#ffffff0d;padding:12px;border-radius:10px;border:1px solid #ffffff30;color:inherit}.entries{display:grid;gap:14px}.entry{padding:18px;background:#ffffff08;border:1px solid #ffffff1a;border-radius:14px;min-width:0}.entry-heading{display:flex;gap:12px;align-items:center}.entry-heading>div{min-width:0}h2{font-size:1.1rem;font-weight:650;overflow-wrap:anywhere}p,small{overflow-wrap:anywhere}.art{font-size:2rem;background:#ffffff0d;padding:12px 20px;border-radius:10px}.entry-heading p,.entry-heading small{color:var(--color-armonia-muted)}.state{margin:12px 0;font-weight:600}.file{display:flex;flex-direction:column;gap:8px;margin:12px 0;font-size:.9rem}.file input{max-width:100%;min-width:0}.filename{font-size:.85rem;color:var(--color-armonia-muted)}button{border:1px solid #ffffff35;padding:9px 13px;border-radius:9px}button.primary{background:var(--color-armonia-accent);color:#121015;font-weight:650;border-color:transparent}button.remove{margin-left:8px}button:disabled{opacity:.45}.empty{padding:30px 0;color:var(--color-armonia-muted)}[role=alert]{color:#fca5a5;margin:10px 0}[role=status]{margin:10px 0;color:var(--color-armonia-muted)}@media(min-width:768px){.inbox{padding:28px 32px 48px}}@media(max-width:400px){button.remove{margin:8px 0 0;display:block}}
</style>
