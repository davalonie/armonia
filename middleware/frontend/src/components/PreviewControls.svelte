<script>
  import {previewState,playing,togglePlayPause,stopPreview} from '../lib/stores/playerStore.js';
</script>
{#if $previewState}
  <div class="preview-controls" aria-label="Controles de preescucha">
    <span>{$previewState.track.title}<small>{$previewState.note}</small></span>
    <span role="status">{$previewState.status==='loading'?'Cargando…':$playing?'Escuchando':'En pausa'}</span>
    <button on:click={togglePlayPause}>{$playing?'Pausar fragmento':'Repetir fragmento'}</button>
    <button on:click={()=>stopPreview()}>Volver a mi reproduccion</button>
  </div>
{/if}
<style>.preview-controls{position:sticky;bottom:0;background:#252031;border:1px solid #786687;border-radius:.65rem;padding:.6rem;display:flex;gap:.5rem;flex-wrap:wrap;align-items:center;z-index:2}.preview-controls span{flex:1;min-width:90px;font-size:.85rem}small{display:block}button{padding:.6rem;border:1px solid #786687;border-radius:.4rem}</style>
