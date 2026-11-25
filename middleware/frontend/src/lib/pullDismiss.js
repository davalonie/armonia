// Pull down to close, as the app's expanded player (ui/player/PlayerPane.kt): what is pulled follows
// the finger downwards (never upwards); letting go closes it when it travelled more than 120 dp or
// was flung down faster than 1600 px/s (Compose measures physical pixels, so 1600 / devicePixelRatio
// CSS px/s), and otherwise it goes back with Compose's default spring (no bounce, stiffness 1500).
// A gesture that starts sideways is left to the cover's swipe (trackSwipe) or to the list.
export const SLOP = 8, DISMISS = 120, FLING = 1600, STIFFNESS = 1500;

/** The release rule of PlayerPane: pull in CSS px (= dp), velocity in CSS px/s, positive downwards. */
export function shouldDismiss(pull, velocity, dpr = 1) {
  return pull > DISMISS || velocity * dpr > FLING;
}

/** Compose's spring(dampingRatio = 1, stiffness = 1500) from `from` to 0 with no initial velocity. */
export function springOffset(from, seconds) {
  const omega = Math.sqrt(STIFFNESS);
  return from * (1 + omega * seconds) * Math.exp(-omega * seconds);
}

/** Velocity in px/s over the samples of the last 100 ms, as Compose's tracker does. */
export function velocityOf(samples) {
  if (samples.length < 2) return 0;
  const first = samples[0], last = samples[samples.length - 1];
  return last.t > first.t ? (last.y - first.y) / (last.t - first.t) * 1000 : 0;
}

/**
 * options: enabled, onPull(offset) for every new offset (drag and spring), onDismiss(), and
 * ignore, a selector of elements where a gesture must not start (sliders, inputs).
 */
export function pullDismiss(node, options) {
  let start = null, dragging = false, offset = 0, samples = [], spring = 0, suppressUntil = 0;
  const show = value => { offset = value; options.onPull?.(value); };
  function down(e) {
    if (!options.enabled || e.pointerType === 'mouse' || !e.isPrimary) return;
    if (options.ignore && e.target.closest(options.ignore)) return;
    cancelAnimationFrame(spring);
    start = {x: e.clientX, y: e.clientY, id: e.pointerId, from: offset};
    dragging = false;
    samples = [{y: e.clientY, t: e.timeStamp}];
  }
  function move(e) {
    if (!start || e.pointerId !== start.id) return;
    const dx = e.clientX - start.x, dy = e.clientY - start.y;
    if (!dragging) {
      if (Math.abs(dx) > SLOP && Math.abs(dx) > Math.abs(dy)) { start = null; return; }
      if (Math.abs(dy) <= SLOP) return;
      dragging = true;
      start.y += Math.sign(dy) * SLOP;   // Compose hands over only the motion past the touch slop.
      node.setPointerCapture?.(e.pointerId);
    }
    samples.push({y: e.clientY, t: e.timeStamp});
    while (samples.length > 2 && e.timeStamp - samples[0].t > 100) samples.shift();
    show(Math.max(0, start.from + e.clientY - start.y));
  }
  function release(e, cancelled) {
    if (!start || e.pointerId !== start.id) return;
    start = null;
    if (!dragging) return;
    dragging = false;
    suppressUntil = performance.now() + 400;
    if (!cancelled && shouldDismiss(offset, velocityOf(samples), devicePixelRatio || 1)) {
      options.onDismiss();
      return;
    }
    back();
  }
  function back() {
    const from = offset, began = performance.now();
    if (!from) return;
    const step = now => {
      const x = springOffset(from, (now - began) / 1000);
      if (x < .5) { show(0); return; }
      show(x);
      spring = requestAnimationFrame(step);
    };
    spring = requestAnimationFrame(step);
  }
  const up = e => release(e, false), cancel = e => release(e, true);
  // The tap that ends a pull must not press the button it started on.
  function click(e) { if (performance.now() < suppressUntil) { e.preventDefault(); e.stopImmediatePropagation(); } }
  node.addEventListener('pointerdown', down);
  node.addEventListener('pointermove', move);
  node.addEventListener('pointerup', up);
  node.addEventListener('pointercancel', cancel);
  node.addEventListener('click', click, true);
  return {
    update(next) {
      options = next;
      // Closed some other way (the caret, Back): start from rest next time.
      if (!options.enabled) { cancelAnimationFrame(spring); start = null; dragging = false; offset = 0; }
    },
    destroy() {
      cancelAnimationFrame(spring);
      node.removeEventListener('pointerdown', down);
      node.removeEventListener('pointermove', move);
      node.removeEventListener('pointerup', up);
      node.removeEventListener('pointercancel', cancel);
      node.removeEventListener('click', click, true);
    },
  };
}
