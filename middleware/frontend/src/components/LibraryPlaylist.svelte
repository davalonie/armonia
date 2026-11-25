<script>
  // A playlist of the library on the phone, opened from Inicio or from Biblioteca: one screen for
  // Navidrome playlists and for mixed lists (library and external songs). Cover, search and order,
  // «Añadir a esta lista» and song menus are the same; a mixed list adds the options of the app's
  // MixedDetail (add the song that plays, rename, export, delete) and moves its songs up and down.
  import {createEventDispatcher,onMount,tick} from 'svelte';
  import {get} from 'svelte/store';
  import {mobile} from '../lib/native.js';
  import {api,toQueueTrack,fromQueueTrack} from '../lib/homelab.js';
  import {currentTrack} from '../lib/stores/playerStore.js';
  import {showContextMenu} from '../lib/stores/contextMenuStore.js';
  import {showToast} from '../lib/stores/toastStore.js';
  import PhonePlaylist from './PhonePlaylist.svelte';
  import PhoneAddSongs from './PhoneAddSongs.svelte';

  export let id;
  export let title='';
  export let kind='local';
  const dispatch=createEventDispatcher();
  let songs=[],cover=null,adding=false,token=0,busy=false;
  let mixed=null;            // the stored mixed list, with its revision
  let dialog=null,dialogEl,newName='',nameField;

  async function load(){
    const mine=++token;
    if(kind==='mixed'){
      try{
        const list=await api.playlist(id);
        if(mine!==token)return;
        mixed=list;title=list.name;cover=list.coverArt||null;
        songs=list.items.map(({track})=>toQueueTrack(track));
      }catch(e){showToast(e.message,'error');}
      return;
    }
    const publish=list=>{if(mine!==token||!list)return;songs=list.entry||[];cover=list.coverArt||null;title=list.name||title;};
    const cached=(await mobile.playlists({id,cached:true}).catch(()=>({}))).playlist;
    publish(cached);
    try{publish((await mobile.playlists({id})).playlist);}
    catch(e){if(!cached)showToast(e.message,'error');}
  }
  onMount(load);
  function added(){adding=false;void load();}

  // Every change reads the list again first, so a change made elsewhere is never overwritten.
  async function change(edit,done=''){
    if(busy)return;busy=true;
    try{const fresh=await api.playlist(id);mixed=await api.save(edit(fresh));if(done)showToast(done);}
    catch(e){showToast(e.message,'error');}
    finally{busy=false;await load();}
  }
  const key=t=>`${t.source}:${t.source_id}`;
  function append(track,p){return p.items.some(i=>key(i.track)===key(track))?p:{...p,items:[...p.items,{id:crypto.randomUUID(),track}]};}
  function move(i,d){return change(p=>{const items=[...p.items];[items[i],items[i+d]]=[items[i+d],items[i]];return {...p,items};});}
  const rowMenu=kind==='mixed'?(song,i)=>[
    {label:'Subir',disabled:i===0||busy,action:()=>move(i,-1)},
    {label:'Bajar',disabled:i===songs.length-1||busy,action:()=>move(i,1)},
    {label:'Quitar de la lista',micon:'remove_circle_outline',disabled:busy,action:()=>change(p=>({...p,items:p.items.filter((_,n)=>n!==i)}))},
  ]:null;

  // «Añadir canciones» writes into the mixed list instead of a Navidrome playlist.
  const mixedStore={
    ids:async()=>(await api.playlist(id)).items.filter(i=>i.track.source==='navidrome').map(i=>i.track.source_id),
    append:async song=>{const p=await api.playlist(id);await api.save(append(fromQueueTrack(song),p));},
    removeLast:async songId=>{
      const p=await api.playlist(id),at=p.items.map(i=>key(i.track)).lastIndexOf('navidrome:'+songId);
      if(at>=0)await api.save({...p,items:p.items.filter((_,n)=>n!==at)});
    },
  };

  function headMenu(anchor){
    const now=get(currentTrack);
    showContextMenu(anchor,[
      {label:'Añadir la cancion que suena',disabled:busy||!now,action:()=>change(p=>append(fromQueueTrack(now),p),'Cancion añadida')},
      {label:'Renombrar',micon:'edit',disabled:busy,action:()=>ask('rename')},
      {label:'Exportar copia a Navidrome',disabled:busy,action:exportCopy},
      {label:'Eliminar playlist',micon:'delete',danger:true,disabled:busy,action:()=>ask('delete')},
    ]);
  }
  async function exportCopy(){
    busy=true;
    try{const p=await api.playlist(id),r=await api.export(p);showToast(`Copia creada en Navidrome: ${r.exported} canciones; ${r.omitted} externas omitidas.`);}
    catch(e){showToast(e.message,'error');}
    finally{busy=false;}
  }
  async function ask(which){
    dialog=which;newName=title;
    await tick();dialogEl?.showModal();
    if(which==='rename')nameField?.select();
  }
  function closeDialog(){dialogEl?.close();dialog=null;}
  async function confirm(){
    const which=dialog;closeDialog();
    if(which==='rename'&&newName.trim())await change(p=>({...p,name:newName.trim()}));
    if(which==='delete'){
      busy=true;
      try{await api.remove(await api.playlist(id));dispatch('back');}
      catch(e){showToast(e.message,'error');}
      finally{busy=false;}
    }
  }
</script>

<PhonePlaylist {title} {songs} playlistId={id} {cover} {kind} {rowMenu} menu={kind==='mixed'?headMenu:null} onRefresh={load} on:back={()=>dispatch('back')}>
  <button class="add-song" on:click={()=>adding=true}><i class="ph ph-plus"></i>Añadir a esta lista</button>
</PhonePlaylist>
{#if adding}<PhoneAddSongs {id} name={title} list={kind==='mixed'?mixedStore:null} on:close={added} />{/if}

{#if dialog}
  <!-- The app's AlertDialog: rounded panel, title, a field when renaming, text buttons at the end. -->
  <dialog bind:this={dialogEl} class="alert" on:close={()=>dialog=null}>
    <h2>{dialog==='rename'?'Renombrar playlist':'¿Eliminar la playlist?'}</h2>
    {#if dialog==='rename'}
      <label class="name"><span>Nombre</span><input bind:this={nameField} bind:value={newName} maxlength="150" on:keydown={e=>e.key==='Enter'&&confirm()}></label>
    {/if}
    <div class="buttons">
      <button on:click={closeDialog}>Cancelar</button>
      <button disabled={dialog==='rename'&&!newName.trim()} on:click={confirm}>{dialog==='rename'?'Guardar':'Eliminar'}</button>
    </div>
  </dialog>
{/if}

<style>
  .alert{margin:auto;width:min(560px,calc(100vw - 48px));padding:24px;border:0;border-radius:28px;background:#242424;color:#eee}
  .alert::backdrop{background:#00000052}
  h2{font-size:24px;line-height:32px;font-weight:400;margin-bottom:16px}
  .name{position:relative;display:block;margin-bottom:8px}
  .name span{position:absolute;top:-8px;left:12px;padding:0 4px;background:#242424;font-size:12px;line-height:16px;color:#c4a3ff}
  .name input{width:100%;height:56px;padding:0 16px;border:2px solid #c4a3ff;border-radius:4px;background:transparent;font-size:16px;color:#eee;outline:0}
  .buttons{display:flex;justify-content:flex-end;gap:8px;margin-top:16px}
  .buttons button{height:40px;padding:0 12px;border-radius:20px;font-size:14px;font-weight:500;letter-spacing:.1px;color:#c4a3ff}
  .buttons button:disabled{opacity:.38}
</style>
