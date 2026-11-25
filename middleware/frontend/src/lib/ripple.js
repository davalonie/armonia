// The Material ripple of the app on everything that can be pressed with a finger, drawn from one
// place so no screen has to remember it. As Compose does it:
//  - an icon-only button without a background (IconButton) gets a circle of 20 dp around its centre,
//    not clipped by the button;
//  - anything else is clipped to its own shape and the wave grows from the finger;
//  - the colour is the element's content colour at 10 % (pressed state layer), it grows in 225 ms,
//    fades in over 75 ms and, once the finger is lifted, fades out over 150 ms.
// The wave is a layer inside the element (Compose draws the indication in the node): it goes with the
// element when it is unmounted, and it is dropped at once when the screen changes. No layout or style
// of the element changes: the layer is positioned against whatever contains it.
// In a scrollable list the press shows after 100 ms (Compose's delayPressInteraction with the tap
// timeout), so a finger that starts scrolling never lights a row. The bottom bar has no wave.
import {currentView} from './stores/viewStore.js';

const TAP_TIMEOUT = 100;
const PRESSABLE = 'button,[role=button],[role=menuitem],[role=tab],[role=option],a[href],summary,select';
const GROW_MS = 225, FADE_IN_MS = 75, FADE_OUT_MS = 150, ALPHA = .10, ICON_RADIUS = 20, SLOP = 10;

function iconOnly(el) {
  return !el.textContent.trim() && !!el.querySelector('svg,i,img');
}

function transparent(colour) {
  return colour === 'transparent' || /rgba\(.*,\s*0\)$/.test(colour);
}

function press(el, e) {
  const rect = el.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  const style = getComputedStyle(el);
  const unbounded = iconOnly(el) && transparent(style.backgroundColor);
  const layer = document.createElement('armonia-ripple');
  const wave = document.createElement('span');
  layer.setAttribute('aria-hidden', 'true');
  let size, x, y;
  if (unbounded) {
    const cx = rect.left + rect.width / 2, cy = rect.top + rect.height / 2;
    size = ICON_RADIUS * 2;
    Object.assign(layer.style, {left: cx - ICON_RADIUS + 'px', top: cy - ICON_RADIUS + 'px', width: size + 'px', height: size + 'px', borderRadius: '50%'});
    x = ICON_RADIUS; y = ICON_RADIUS;
  } else {
    Object.assign(layer.style, {left: rect.left + 'px', top: rect.top + 'px', width: rect.width + 'px', height: rect.height + 'px', borderRadius: style.borderRadius});
    x = e.clientX - rect.left; y = e.clientY - rect.top;
    size = 2 * Math.hypot(Math.max(x, rect.width - x), Math.max(y, rect.height - y));
  }
  Object.assign(layer.style, {position: 'absolute', zIndex: 2147483000, overflow: 'hidden', pointerEvents: 'none', contain: 'strict'});
  Object.assign(wave.style, {
    position: 'absolute', left: x - size / 2 + 'px', top: y - size / 2 + 'px', width: size + 'px', height: size + 'px',
    borderRadius: '50%', background: style.color, opacity: '0', transform: 'scale(.2)',
    transition: `transform ${GROW_MS}ms cubic-bezier(.4,0,.2,1), opacity ${FADE_IN_MS}ms linear`,
  });
  layer.appendChild(wave);
  // Inside the element (a select cannot hold children: its parent then). Placed from where the
  // containing block really is, so the element keeps its own position and styles.
  const host = el.tagName === 'SELECT' ? el.parentElement : el;
  const left = parseFloat(layer.style.left), top = parseFloat(layer.style.top);
  Object.assign(layer.style, {left: '0px', top: '0px'});
  host.appendChild(layer);
  const origin = layer.getBoundingClientRect();
  Object.assign(layer.style, {left: left - origin.left + 'px', top: top - origin.top + 'px'});
  requestAnimationFrame(() => { wave.style.opacity = String(ALPHA); wave.style.transform = 'scale(1)'; });
  return {layer, wave, started: performance.now(), x: e.clientX, y: e.clientY, id: e.pointerId};
}

function release(ripple, done = () => {}) {
  const wait = Math.max(0, GROW_MS - (performance.now() - ripple.started));
  setTimeout(() => {
    if (!ripple.layer.isConnected) { done(); return; }
    ripple.wave.style.transition = `opacity ${FADE_OUT_MS}ms linear`;
    ripple.wave.style.opacity = '0';
    setTimeout(() => { ripple.layer.remove(); done(); }, FADE_OUT_MS + 20);
  }, wait);
}

/** Inside something that scrolls (a list, the page): Compose then waits the tap timeout. */
export function inScrollable(el) {
  for (let node = el.parentElement; node && node !== document.documentElement; node = node.parentElement) {
    const style = getComputedStyle(node);
    if (/(auto|scroll)/.test(style.overflowY + style.overflowX)) return true;
  }
  return false;
}

export function installRipple(root = document) {
  let current = null, waiting = null;
  const live = new Set();
  const drop = ripple => { ripple.layer.remove(); live.delete(ripple); };
  const show = (el, e) => { const ripple = press(el, e); if (ripple) live.add(ripple); return ripple; };
  const end = () => {
    if (waiting) {
      // Lifted before the tap timeout: Compose still shows the press, then releases it.
      clearTimeout(waiting.timer);
      const ripple = show(waiting.el, waiting.e);
      waiting = null;
      if (ripple) release(ripple, () => live.delete(ripple));
      return;
    }
    if (current) { const ripple = current; release(ripple, () => live.delete(ripple)); current = null; }
  };
  const cancel = () => {
    if (waiting) { clearTimeout(waiting.timer); waiting = null; }
    if (current) { drop(current); current = null; }
  };
  root.addEventListener('pointerdown', e => {
    end();
    // Touch and pen only: a desktop mouse keeps its hover colours.
    if (e.pointerType === 'mouse' || !e.isPrimary) return;
    const el = e.target.closest?.(PRESSABLE);
    if (!el || el.disabled || el.getAttribute('aria-disabled') === 'true' || el.closest('[data-no-ripple]')) return;
    if (!inScrollable(el)) { current = show(el, e); return; }
    const pressAt = {clientX: e.clientX, clientY: e.clientY, pointerId: e.pointerId};
    waiting = {el, e: pressAt, x: e.clientX, y: e.clientY, id: e.pointerId,
      timer: setTimeout(() => { const w = waiting; waiting = null; if (w) current = show(w.el, w.e); }, TAP_TIMEOUT)};
  }, {capture: true, passive: true});
  root.addEventListener('pointermove', e => {
    // Scrolling or swiping is not a press: the wave goes at once (or never comes).
    const pressed = current || waiting;
    if (pressed && e.pointerId === pressed.id && Math.hypot(e.clientX - pressed.x, e.clientY - pressed.y) > SLOP) cancel();
  }, {capture: true, passive: true});
  root.addEventListener('pointerup', end, {capture: true, passive: true});
  root.addEventListener('pointercancel', cancel, {capture: true, passive: true});
  addEventListener('scroll', cancel, {capture: true, passive: true});
  // A new screen: no wave of the old one survives on it.
  let first = true;
  currentView.subscribe(() => {
    if (first) { first = false; return; }
    cancel();
    for (const ripple of [...live]) drop(ripple);
  });
}
