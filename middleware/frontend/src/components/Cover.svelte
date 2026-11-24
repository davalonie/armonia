<script>
  import {artUrl} from '../lib/homelab.js';
  export let covers=[];        // track references or image URLs
  export let variant='plain';  // plain | liked | weekly | mix | artist
  export let label='';
  export let size=300;
  $: urls=[...new Set(covers.map(c=>artUrl(c,size)).filter(Boolean))];
  // Generated lists use one image under their own band; ordinary lists a 2×2 mosaic when four exist.
  $: tiles=variant==='plain'&&urls.length>=4?urls.slice(0,4):urls.slice(0,1);
  $: hue=[...label].reduce((n,c)=>(n*31+c.charCodeAt(0))%70,0)+250;
</script>

<div class="cover {variant}" class:mosaic={tiles.length===4} style="--hue:{hue}">
  {#if variant==='liked'}
    <i aria-hidden="true" class="ph-fill ph-heart"></i>
  {:else}
    <i aria-hidden="true" class="ph {variant==='artist'?'ph-user':variant==='album'?'ph-disc':'ph-music-notes'} placeholder"></i>
    {#each tiles as url (url)}<img src={url} alt="" loading="lazy" referrerpolicy="no-referrer" on:error={e=>e.currentTarget.style.visibility='hidden'}>{/each}
    {#if variant==='weekly'||variant==='mix'}
      <span class="tint" aria-hidden="true"></span>
      <i aria-hidden="true" class="ph-fill {variant==='weekly'?'ph-sparkle':'ph-waveform'} spark"></i>
      <span class="band" aria-hidden="true"><small>{variant==='weekly'?'Cada semana':'Mix'}</small><b>{label}</b></span>
    {/if}
  {/if}
</div>

<style>
  .cover{position:relative;width:100%;aspect-ratio:1;overflow:hidden;border-radius:6px;background:#2a2433;display:grid;place-items:center;box-shadow:0 8px 24px rgba(0,0,0,.35);container-type:inline-size}
  .cover.artist{border-radius:50%}
  .cover img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
  .cover.mosaic img{position:static;aspect-ratio:1}
  .cover.mosaic{grid-template-columns:1fr 1fr;place-items:stretch}
  .cover.mosaic .placeholder{display:none}
  .placeholder{font-size:34cqw;color:#ffffff40}
  .cover.liked{background:linear-gradient(135deg,#5b2dd6,#a78bfa 65%,#c9f2e4)}
  .cover.liked i{font-size:38cqw;color:#fff}
  .tint{position:absolute;inset:0;background:linear-gradient(180deg,hsl(var(--hue) 70% 45% / .25),hsl(var(--hue) 75% 22% / .92) 78%)}
  .cover.weekly:not(:has(img)),.cover.mix:not(:has(img)){background:linear-gradient(140deg,hsl(var(--hue) 70% 50%),hsl(var(--hue) 60% 18%))}
  .band{position:absolute;left:8cqw;right:30cqw;bottom:8cqw;display:flex;flex-direction:column;gap:1cqw;text-align:left;color:#fff;border-left:2cqw solid var(--color-armonia-accent);padding-left:5cqw}
  .band small{font-size:max(6cqw,7px);letter-spacing:.08em;text-transform:uppercase;opacity:.85;font-weight:600}
  .band b{font-size:max(10.5cqw,9px);line-height:1.1;font-weight:800;display:-webkit-box;-webkit-line-clamp:2;line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
  .spark{display:none;position:relative;font-size:46cqw;color:#fff}
  /* Shortcut-sized covers: the wordmark would be illegible, so a single glyph identifies a generated list. */
  @container (max-width:90px){.band{display:none}.spark{display:block}}
</style>
