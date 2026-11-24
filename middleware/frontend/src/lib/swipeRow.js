// The Android row gesture commits on release after 72 dp. Vertical motion keeps scrolling the list.
export function swipeRow(node, options) {
  let start, distance = 0, suppressUntil = 0;
  function reset() {
    start = null;
    distance = 0;
    node.style.translate = '';
  }
  function down(e) {
    if (!options.enabled || e.pointerType === 'mouse' || !e.isPrimary || e.target.closest('button:not([data-swipe-handle]),input,select,a')) return;
    start = {x:e.clientX,y:e.clientY,id:e.pointerId};
  }
  function move(e) {
    if (!start || e.pointerId !== start.id) return;
    const dx = e.clientX - start.x, dy = e.clientY - start.y;
    if (Math.abs(dy) > 10 && Math.abs(dy) >= Math.abs(dx)) { reset(); return; }
    distance = options.both ? dx : Math.max(0,dx);
    if (Math.abs(distance) > 10) {
      node.setPointerCapture(e.pointerId);
      node.style.translate = Math.max(-100,Math.min(100,distance))+'px 0';
    }
  }
  function up(e) {
    if (!start || e.pointerId !== start.id) return;
    const commit = Math.abs(distance) >= 72;
    if (Math.abs(distance) > 10) suppressUntil = performance.now()+400;
    reset();
    if (commit) options.commit();
  }
  function click(e) {
    if (performance.now() < suppressUntil) { e.preventDefault();e.stopImmediatePropagation(); }
  }
  node.addEventListener('pointerdown',down);
  node.addEventListener('pointermove',move);
  node.addEventListener('pointerup',up);
  node.addEventListener('pointercancel',reset);
  node.addEventListener('click',click,true);
  return {
    update(next){options=next;},
    destroy(){
      node.removeEventListener('pointerdown',down);
      node.removeEventListener('pointermove',move);
      node.removeEventListener('pointerup',up);
      node.removeEventListener('pointercancel',reset);
      node.removeEventListener('click',click,true);
    }
  };
}
