<script>
  // Fast-scroll bar, as in the app: on lists of more than 50 items a bar appears on the right while scrolling and
  // hides 1.5 s after it stops. Dragging it jumps through the list; a bubble says where you are in the current order.
  // The page scrolls in <main id="view">; `list` is the element whose children are the items, in order.
  import {onMount,onDestroy} from 'svelte';
  export let labels=[];
  export let list=null;
  let scroller=null,track,visible=false,dragging=false,index=0,hideTimer;
  $: active=labels.length>50&&!!list;
  $: if(index>labels.length-1)index=Math.max(0,labels.length-1);
  $: fraction=labels.length>1?index/(labels.length-1):0;

  const shown=()=>!!list?.offsetParent;   // views stay mounted while hidden
  function firstVisible(){
    const items=list.children,top=scroller.getBoundingClientRect().top;
    let lo=0,hi=Math.min(labels.length,items.length)-1;
    while(lo<hi){const mid=(lo+hi)>>1;if(items[mid].getBoundingClientRect().bottom<=top+1)lo=mid+1;else hi=mid;}
    return Math.max(0,lo);
  }
  function show(){visible=true;clearTimeout(hideTimer);if(!dragging)hideTimer=setTimeout(()=>{visible=false;},1500);}
  function onScroll(){
    if(!active||dragging||!shown())return;
    const r=list.getBoundingClientRect(),s=scroller.getBoundingClientRect();
    if(r.bottom<s.top||r.top>s.bottom){visible=false;return;}
    index=firstVisible();show();
  }
  function jump(y){
    const t=track.getBoundingClientRect(),f=Math.min(1,Math.max(0,(y-t.top)/t.height));
    index=Math.round(f*(labels.length-1));
    const item=list.children[index];
    if(item)scroller.scrollTop+=item.getBoundingClientRect().top-scroller.getBoundingClientRect().top-8;
  }
  function down(e){dragging=true;e.currentTarget.setPointerCapture?.(e.pointerId);jump(e.clientY);show();e.preventDefault();}
  function move(e){if(dragging)jump(e.clientY);}
  function up(){if(!dragging)return;dragging=false;show();}
  onMount(()=>{scroller=document.getElementById('view');scroller?.addEventListener('scroll',onScroll,{passive:true});});
  onDestroy(()=>{scroller?.removeEventListener('scroll',onScroll);clearTimeout(hideTimer);});
</script>

{#if active}
  <div class="fast" class:visible bind:this={track} aria-hidden="true">
    <div class="thumb" style:top="calc({fraction} * (100% - 44px))" on:pointerdown={down} on:pointermove={move} on:pointerup={up} on:pointercancel={up}>
      {#if dragging}<span class="bubble">{labels[index]}</span>{/if}
      <span class="bar"></span>
    </div>
  </div>
{/if}

<style>
  .fast{position:fixed;right:2px;top:84px;bottom:170px;width:36px;z-index:45;opacity:0;pointer-events:none;transition:opacity .2s}
  @media(min-width:768px){.fast{bottom:110px}}
  .fast.visible{opacity:1;pointer-events:auto}
  .thumb{position:absolute;right:0;width:36px;height:44px;display:flex;align-items:center;justify-content:flex-end;cursor:grab;touch-action:none}
  .thumb:active{cursor:grabbing}
  .bar{width:7px;height:100%;border-radius:4px;background:var(--color-armonia-accent)}
  .bubble{position:absolute;right:44px;white-space:nowrap;padding:4px 10px;border-radius:8px;background:#2c2537;color:#fff;font-size:.9rem;font-weight:700;box-shadow:0 4px 14px #0008}
</style>
