<script>
  import {onDestroy} from 'svelte';
  import {mobileImport} from '../lib/native.js';
  import {showToast} from '../lib/stores/toastStore.js';
  import ImportReview from '../components/ImportReview.svelte';
  import {currentView,showView} from '../lib/stores/viewStore.js';
  import {stopPreview} from '../lib/stores/playerStore.js';
  let active=false;
  $: if($currentView==='import-review')active=true;
  else if(active){active=false;stopPreview();}
  onDestroy(()=>{if(active)stopPreview();});
</script>
<section class="phone-import">
  <header class="phone-toolbar"><button class="phone-back" data-phone-back aria-label="Volver" on:click={()=>showView('library')}><i class="ph ph-arrow-left"></i></button><h1>Importar playlist</h1></header>
  <ImportReview visible={$currentView==='import-review'} onOpenPending={()=>showView('manual-inbox')} onImportAll={()=>mobileImport.openBulkImport().catch(()=>showToast('No se pudo abrir la importación en el navegador.','error'))}/>
</section>
