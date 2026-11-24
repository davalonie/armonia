import {mobile} from './native.js';

// Only the innermost visible screen at its upper scroll limit handles the pull.
export function pullRefresh(node, refresh) {
  if (!mobile) return;
  let start, busy = false;
  node.dataset.pullRefresh = '';
  function touchStart(event) {
    const scroller = node.closest('main') || document.scrollingElement;
    const touch = event.touches[0];
    start = !busy && event.touches.length===1 && scroller.scrollTop<=0 &&
      event.target.closest('[data-pull-refresh]')===node ? {x:touch.clientX,y:touch.clientY} : null;
  }
  function cancel() { start=null; }
  async function touchEnd(event) {
    if (!start) return;
    const touch=event.changedTouches[0], dy=touch.clientY-start.y, dx=touch.clientX-start.x;
    cancel();
    if (dy < 80 || dy < 2*Math.abs(dx)) return;
    busy=true;
    try { await refresh(); } finally { busy=false; }
  }
  node.addEventListener('touchstart',touchStart,{passive:true});
  node.addEventListener('touchend',touchEnd,{passive:true});
  node.addEventListener('touchcancel',cancel);
  return {update(next){refresh=next;},destroy(){
    node.removeEventListener('touchstart',touchStart);
    node.removeEventListener('touchend',touchEnd);
    node.removeEventListener('touchcancel',cancel);
    delete node.dataset.pullRefresh;
  }};
}
