// Swipe gestures of song rows. Vertical motion keeps scrolling the list.
//
// Rightwards (the default) is the app's SwipeToQueue (ui/components/SwipeToQueue.kt): the row
// follows the finger up to 132 dp; behind it, the accent shows the queue icon, then «A la cola»
// after 60 % of the 72 dp threshold, and «Suelta» with a stronger accent and a tick once letting go
// will queue the song. Letting go springs the row back as Compose's animate() does.
//
// `both` (the queue sheet) is the app's SwipeToDismissBox (material3 1.4.0): the row follows the
// finger to either side and is removed past 56 dp, or when flung faster than 125 dp/s towards
// that side. Unlike the app, and as the user asked, the error red of the theme with a bin shows
// underneath while it slides.
import {mobile} from './native.js';

const SLOP = 8, THRESHOLD = 72, LIMIT = 132;
export const REMOVE_AT = 56, REMOVE_FLING = 125, ERROR_RED = '#FF5449';
const DELETE_ICON = 'M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z';

/** SwipeToDismissBox's decision: offset in dp, velocity in dp/s (both signed, positive to the right). */
export function removes(offset, velocity) {
  if (!offset) return false;
  if (Math.abs(velocity) > REMOVE_FLING) return Math.sign(velocity) === Math.sign(offset);
  return Math.abs(offset) >= REMOVE_AT;
}
const ACCENT = '196,163,255';
const QUEUE_ICON = 'M15 6H3v2h12V6zm0 4H3v2h12v-2zM3 16h8v-2H3v2zM17 6v8.18c-.31-.11-.65-.18-1-.18-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3V8h3V6h-5z';

function tick() {
  mobile?.command({action: 'haptic'}).catch(() => {});
}

// What shows behind the row: placed to the left of the row, so it stays where the row was while
// the row slides over it.
function removeLayer() {
  const layer = document.createElement('span');
  layer.setAttribute('aria-hidden', 'true');
  layer.className = 'swipe-remove';
  layer.style.cssText = `position:absolute;top:0;bottom:0;display:flex;align-items:center;padding:0 16px;overflow:hidden;pointer-events:none;background:${ERROR_RED};color:#000`;
  layer.innerHTML = `<svg viewBox="0 0 24 24" width="24" height="24"><path fill="currentColor" d="${DELETE_ICON}"/></svg>`;
  return layer;
}

function revealLayer() {
  const layer = document.createElement('span');
  layer.setAttribute('aria-hidden', 'true');
  layer.style.cssText = 'position:absolute;top:0;bottom:0;display:flex;align-items:center;gap:8px;padding-left:20px;overflow:hidden;white-space:nowrap;pointer-events:none;'
    + `color:rgb(${ACCENT});font-size:12px;line-height:16px;font-weight:500;letter-spacing:.5px`;
  layer.innerHTML = `<svg viewBox="0 0 24 24" width="24" height="24" style="flex:none"><path fill="currentColor" d="${QUEUE_ICON}"/></svg><span></span>`;
  return layer;
}

export function swipeRow(node, options) {
  let start = null, dragging = false, distance = 0, suppressUntil = 0, armed = false, layer = null, spring = 0, samples = [];

  // The red stays where the row was (the parent clips it) while the row slides over it.
  function paintRemove(offset) {
    if (!offset) {
      node.style.translate = ''; node.style.transition = '';
      layer?.remove(); layer = null;
      return;
    }
    if (!layer) {
      layer = removeLayer();
      if (getComputedStyle(node).position === 'static') node.style.position = 'relative';
      node.style.transition = 'none';
      node.appendChild(layer);
    }
    node.style.translate = offset + 'px 0';
    Object.assign(layer.style, offset > 0
      ? {left: -offset + 'px', right: '', width: offset + 'px', justifyContent: 'flex-start'}
      : {left: '', right: offset + 'px', width: -offset + 'px', justifyContent: 'flex-end'});
  }

  function paint(offset) {
    distance = offset;
    if (options.both) { paintRemove(offset); return; }
    if (offset <= 0) {
      node.style.translate = ''; node.style.position = ''; node.style.background = ''; node.style.transition = '';
      layer?.remove(); layer = null;
      return;
    }
    if (!layer) {
      layer = revealLayer();
      if (getComputedStyle(node).position === 'static') node.style.position = 'relative';
      node.style.background = 'var(--color-armonia-bg,#121015)';
      // The row's own CSS transitions would make it lag behind the finger.
      node.style.transition = 'none';
      node.appendChild(layer);
    }
    node.style.translate = offset + 'px 0';
    Object.assign(layer.style, {left: -offset + 'px', width: offset + 'px', background: `rgba(${ACCENT},${armed ? .30 : .12})`});
    layer.lastChild.textContent = offset > THRESHOLD * .6 ? (armed ? 'Suelta' : 'A la cola') : '';
  }
  // Compose's default spring (no bounce, medium stiffness): x(t) = x0 (1 + ωt) e^(−ωt).
  function springBack() {
    cancelAnimationFrame(spring);
    const from = distance, began = performance.now(), omega = Math.sqrt(1500);
    const step = now => {
      const t = (now - began) / 1000, x = from * (1 + omega * t) * Math.exp(-omega * t);
      if (Math.abs(x) < .5) { paint(0); return; }
      paint(x);
      spring = requestAnimationFrame(step);
    };
    spring = requestAnimationFrame(step);
  }
  // Removed: the row leaves to its side over the red, then the queue drops it.
  function slideOut() {
    const from = distance, to = Math.sign(from) * node.offsetWidth, began = performance.now();
    const step = now => {
      const k = Math.min(1, (now - began) / 150);
      paint(from + (to - from) * (1 - (1 - k) ** 2));
      if (k < 1) { spring = requestAnimationFrame(step); return; }
      options.commit();
      // Normally the row is gone with the next queue; if the removal failed it comes back.
      setTimeout(() => { if (node.isConnected && distance) paint(0); }, 1500);
    };
    spring = requestAnimationFrame(step);
  }
  function down(e) {
    if (!options.enabled || e.pointerType === 'mouse' || !e.isPrimary || e.target.closest('button:not([data-swipe-handle]),input,select,a,[data-drag-handle]')) return;
    cancelAnimationFrame(spring); paint(0);
    start = {x: e.clientX, y: e.clientY, id: e.pointerId};
    dragging = false; armed = false;
    samples = [{x: e.clientX, t: e.timeStamp}];
  }
  function move(e) {
    if (!start || e.pointerId !== start.id) return;
    const dx = e.clientX - start.x, dy = e.clientY - start.y;
    if (!dragging) {
      if (Math.abs(dy) > SLOP && Math.abs(dy) >= Math.abs(dx)) { start = null; return; }
      if (Math.abs(dx) <= SLOP || (!options.both && dx < 0)) return;
      dragging = true;
      node.setPointerCapture(e.pointerId);
    }
    if (options.both) {
      samples.push({x: e.clientX, t: e.timeStamp});
      while (samples.length > 2 && e.timeStamp - samples[0].t > 100) samples.shift();
      paint(dx - Math.sign(dx) * SLOP);
      return;
    }
    const offset = Math.max(0, Math.min(LIMIT, dx - SLOP));
    const far = offset >= THRESHOLD;
    if (far !== armed) { armed = far; if (far) tick(); }
    paint(offset);
  }
  function up(e) {
    if (!start || e.pointerId !== start.id) return;
    start = null;
    if (!dragging) return;
    dragging = false;
    suppressUntil = performance.now() + 400;
    if (options.both) {
      const first = samples[0], last = samples[samples.length - 1];
      const velocity = last.t > first.t ? (last.x - first.x) / (last.t - first.t) * 1000 : 0;
      if (removes(distance, velocity)) slideOut(); else springBack();
      return;
    }
    const commit = armed;
    armed = false;
    if (commit) options.commit();
    springBack();
  }
  function cancel() { start = null; dragging = false; armed = false; if (distance) springBack(); }
  function click(e) {
    if (performance.now() < suppressUntil) { e.preventDefault(); e.stopImmediatePropagation(); }
  }
  node.addEventListener('pointerdown', down);
  node.addEventListener('pointermove', move);
  node.addEventListener('pointerup', up);
  node.addEventListener('pointercancel', cancel);
  node.addEventListener('click', click, true);
  return {
    update(next) { options = next; },
    destroy() {
      cancelAnimationFrame(spring);
      layer?.remove();
      node.removeEventListener('pointerdown', down);
      node.removeEventListener('pointermove', move);
      node.removeEventListener('pointerup', up);
      node.removeEventListener('pointercancel', cancel);
      node.removeEventListener('click', click, true);
    },
  };
}
