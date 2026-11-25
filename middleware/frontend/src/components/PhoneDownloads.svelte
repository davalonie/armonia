<script>
  import {onMount,createEventDispatcher} from 'svelte';
  import {mobile} from '../lib/native.js';
  import {nativeTrack} from '../lib/nativeTracks.js';
  import {coverArtUrl,artSize} from '../lib/api.js';
  import Cover from './Cover.svelte';
  import ShuffleToggle from './ShuffleToggle.svelte';
  import PhonePlayButton from './PhonePlayButton.svelte';
  import {playList,beginPlayRequest,offlineProblem} from '../lib/stores/playerStore.js';
  import {showToast} from '../lib/stores/toastStore.js';

  export let id=null, title='', tracks=[], embedded=false, kind='playlist';
  export let caption='';
  const dispatch=createEventDispatcher();
  const all={key:'all',title:'Tus canciones sin conexion'};
  let rows=[],busy=false,loaded=false;
  async function refresh(){if(!document.hidden){rows=(await mobile.downloads()).rows;loaded=true;}}
  onMount(()=>{
    const update=()=>refresh().catch(()=>{});
    void update();
    const timer=setInterval(update,1800);
    return ()=>clearInterval(timer);
  });
  $: selected=rows.find(row=>row.key===kind+':'+id);
  $: status=selected ? (selected.failed?'Reintentar descarga':('En el teléfono · '+selected.done+'/'+selected.total)) : (kind==='album'?'Descargar album':'Descargar playlist');
  $: caption=selected ? status : '';
  async function remove(row){
    busy=true;
    try{await mobile.unpin({key:row.key});await refresh();}
    catch{showToast('No se pudo quitar la descarga.','error');}
    finally{busy=false;}
  }
  async function pin(){
    busy=true;
    try{
      const result=await mobile.pin({id,kind,title,tracks});
      if(result.restricted)showToast('Una canción de la lista no permite la descarga sin conexión.','error');
      else await refresh();
    }
    catch{showToast('No se pudo guardar la colección en el teléfono.','error');}
    finally{busy=false;}
  }
  async function open(row,start=false){
    try{
      const epoch=start?await beginPlayRequest():undefined;
      const result=await mobile.offlineTracks({key:row.key});
      const kind=row.key.split(':')[0];
      const context={from:row.title,playlist:['mixed','playlist'].includes(kind)?row.id:null,playlistKind:kind==='mixed'?'mixed':'local'};
      const automatic=new Set();
      const songs=result.songs.map(song=>nativeTrack(song,context,automatic));
      if(start && songs.length)playList(songs,epoch);
      else dispatch('collection',{row,songs});
    }catch{showToast('No se pudo abrir la descarga.','error');}
  }
</script>

{#if $offlineProblem}<p role="alert">{$offlineProblem}</p>{/if}
{#if id}
  <button class="pin" aria-label={selected&&!selected.failed?'Quitar del teléfono':status} title={status} disabled={busy || (!selected && !tracks.length)} on:click={()=>selected&&!selected.failed?remove(selected):pin()}>
    <i aria-hidden="true" class="ph {selected&&!selected.failed?'ph-check-circle':'ph-arrow-circle-down'}"></i>
  </button>
{:else}
  <section class="phone-downloads" class:embedded aria-label="Descargas del teléfono">
    {#if !embedded}<h2>En el telefono</h2>{/if}
    {#if embedded && loaded && !rows.length}
      <div class="offline-empty"><i class="ph ph-cloud-slash"></i><b>Todavia no has guardado nada sin conexion</b><small>Abre un album o una playlist y toca el icono de descarga. Sonara aqui sin conexion.</small></div>
    {/if}
    {#if embedded && rows.length}
      <div class="offline-actions">
        <ShuffleToggle/><PhonePlayButton label="Reproducir todo" on:click={()=>open(all,true)} /><button class="all-songs" aria-label="Tus canciones sin conexion" title="Tus canciones sin conexion" on:click={()=>open(all)}><i class="ph ph-list"></i></button>
      </div>
      {#each rows as row (row.key)}
        <div class="flex items-center"><button class="offline-collection flex-1" on:click={()=>open(row,row.key.startsWith('song:'))}>
          <span class="art"><Cover covers={row.coverArt?[coverArtUrl(row.coverArt,artSize(48,96,300))]:[]} size={96}/></span>
          <span><b>{row.title}</b><small>{row.subtitle}</small><small>{row.failed ? row.failed+' con error' : row.running ? 'Descargando '+row.done+'/'+row.total : row.done+'/'+row.total+' en el teléfono'}</small></span>
        </button><button class="pin" aria-label={`Quitar ${row.title} del teléfono`} disabled={busy} on:click={()=>remove(row)}><i class="ph ph-minus-circle"></i></button></div>
      {/each}
    {:else if !embedded}
    {#each [all,...rows] as row (row.key)}
      <div class="tile">
        <button class="open" on:click={()=>open(row)}>
          <span class="art"><Cover covers={row.coverArt?[coverArtUrl(row.coverArt,artSize(48,96,300))]:[]} size={96} /></span>
          <span>{row.title}{#if embedded && row.total}<small>{row.done}/{row.total} en el teléfono</small>{/if}</span>
        </button>
        <button class="quick-play" aria-label={`Reproducir ${row.title} sin conexión`} on:click={()=>open(row,true)}><i aria-hidden="true" class="ph-fill ph-play"></i></button>
      </div>
    {/each}{/if}
  </section>
{/if}
<style>
  .pin{height:48px;width:48px;display:grid;place-items:center;font-size:26px;color:#b3b3b3}
  .pin:disabled{color:#aaa}
  .phone-downloads{margin:0 0 24px}
  .embedded{padding:8px 16px}
  h2{font-size:22px;line-height:28px;font-weight:700;margin-bottom:12px}
  .tile{height:56px;display:flex;align-items:center;border-radius:6px;overflow:hidden;background:#ffffff14}
  .tile+.tile{margin-top:8px}
  .open{flex:1;min-width:0;display:flex;align-items:center;gap:8px;text-align:left;font-size:13px;line-height:16px;font-weight:700}
  .art{width:56px;flex:none}
  small{display:block;color:#aaa;font-weight:400}
  .quick-play{min-height:0;flex:none;width:32px;height:32px;border-radius:50%;margin:0 8px 0 4px;background:var(--color-armonia-accent);color:#1a1126;display:grid;place-items:center;font-size:.95rem}
</style>
