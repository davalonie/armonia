// The sideways swipe that changes song in the app (ui/player/TrackSwipe.kt): what is under the
// finger follows it, and letting go changes song when it was pulled 30 % of the width or flung at
// 900 dp/s towards that side; otherwise it goes straight back. A vertical move is left to the page.
// The offset is published as the CSS variable --track-swipe on the node; each screen decides what
// moves with it (the mini player moves its row, the full player its cover).
import {get} from 'svelte/store';
import {nativeSteps} from './stores/nativePlayback.js';
import {swipeTrack} from './stores/playerStore.js';
import {mobile} from './native.js';

const SLOP = 8, MINIMUM = 10, FLING = 900, SHARE = .3;

/** Port of swipeStep(): 1 next, -1 previous, 0 nothing. Velocity in px/s, positive to the right. */
export function swipeStep(offset, width, velocity, fling, minimum, previous, next) {
  if (width <= 0 || Math.abs(offset) < minimum) return 0;
  if (Math.abs(offset) / width < SHARE && (Math.abs(velocity) < fling || velocity * offset <= 0)) return 0;
  if (offset < 0 && next) return 1;
  if (offset > 0 && previous) return -1;
  return 0;
}

export function trackSwipe(node, options = {}) {
  let start = null, dragging = false, offset = 0, samples = [], suppressUntil = 0;
  const show = value => { offset = value; node.style.setProperty('--track-swipe', value + 'px'); };
  function down(e) {
    if (options.enabled === false || e.pointerType === 'mouse' || !e.isPrimary) return;
    start = {x: e.clientX, y: e.clientY, id: e.pointerId};
    dragging = false;
    samples = [{x: e.clientX, t: e.timeStamp}];
  }
  function move(e) {
    if (!start || e.pointerId !== start.id) return;
    const dx = e.clientX - start.x, dy = e.clientY - start.y;
    if (!dragging) {
      if (Math.abs(dy) > SLOP && Math.abs(dy) >= Math.abs(dx)) { start = null; return; }
      if (Math.abs(dx) <= SLOP) return;
      dragging = true;
      node.setPointerCapture?.(e.pointerId);
    }
    const width = node.offsetWidth;
    show(Math.max(-width, Math.min(width, dx)));
    samples.push({x: e.clientX, t: e.timeStamp});
    while (samples.length > 2 && e.timeStamp - samples[0].t > 100) samples.shift();
  }
  function up(e) {
    if (!start || e.pointerId !== start.id) return;
    start = null;
    if (!dragging) return;
    dragging = false;
    suppressUntil = performance.now() + 400;
    const first = samples[0], last = samples[samples.length - 1];
    const velocity = last.t > first.t ? (last.x - first.x) / (last.t - first.t) * 1000 : 0;
    // Without the native player (the web on a phone) the queue itself decides, as before.
    const steps = mobile ? get(nativeSteps) : {previous: true, next: true};
    const step = swipeStep(offset, node.offsetWidth, velocity, FLING, MINIMUM, steps.previous, steps.next);
    show(0);
    if (step) swipeTrack(step);
  }
  function cancel() { start = null; dragging = false; show(0); }
  // The tap that ends a swipe must not open the player or press a button.
  function click(e) { if (performance.now() < suppressUntil) { e.preventDefault(); e.stopImmediatePropagation(); } }
  node.addEventListener('pointerdown', down);
  node.addEventListener('pointermove', move);
  node.addEventListener('pointerup', up);
  node.addEventListener('pointercancel', cancel);
  node.addEventListener('click', click, true);
  return {
    update(next) { options = next; },
    destroy() {
      node.removeEventListener('pointerdown', down);
      node.removeEventListener('pointermove', move);
      node.removeEventListener('pointerup', up);
      node.removeEventListener('pointercancel', cancel);
      node.removeEventListener('click', click, true);
    },
  };
}
