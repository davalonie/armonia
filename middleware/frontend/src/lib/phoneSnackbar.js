// The phone's notices, as the app's Snackbar (MainScreen's Scaffold, material3 1.4.0).
//
// SnackbarHostState shows one at a time: the others wait their turn, in order. A notice with a
// `replace` key is the app's collectLatest: a newer one with the same key takes the place of the one
// showing (or still waiting), as each «añadida a la cola» does with the one before it.
// SnackbarDuration.toMillis: Short 4 s, Long 10 s, counted from the moment it is shown.
import {writable} from 'svelte/store';

export const SHORT = 4000, LONG = 10000;

export function createSnackbarHost({setTimer = setTimeout, clearTimer = clearTimeout} = {}) {
  let current = null, pending = [], timer = null, next = 1;
  const {subscribe, set} = writable(null);
  function advance() {
    clearTimer(timer); timer = null;
    current = pending.shift() || null;
    set(current);
    if (current) { const id = current.id; timer = setTimer(() => dismiss(id), current.duration); }
  }
  function show({message, action = null, long = false, replace = null}) {
    const item = {id: next++, message, action, duration: long ? LONG : SHORT, replace};
    if (replace) pending = pending.filter(p => p.replace !== replace);
    pending.push(item);
    if (!current || (replace && current.replace === replace)) advance();
    return item.id;
  }
  function dismiss(id) {
    if (current?.id === id) advance();
    else pending = pending.filter(p => p.id !== id);
  }
  // «Deshacer»: the action runs once and the notice goes, as SnackbarData.performAction().
  function act(id) {
    if (current?.id !== id) return;
    const {action} = current;
    advance();
    action?.();
  }
  return {subscribe, show, dismiss, act};
}

// FadeInFadeOutWithScale, with the standard MotionScheme the app's theme uses: the opacity follows
// FastEffects, spring(1, 3800), and the scale 0.8 <-> 1 follows FastSpatial, spring(0.9, 1400).
// Both start at rest; Animatable stops within 0.01 of the target.
export const OPACITY = {damping: 1, stiffness: 3800}, SCALE = {damping: .9, stiffness: 1400}, HIDDEN_SCALE = .8;
export const SETTLED = .01;

export function springAt(from, to, seconds, {damping, stiffness}) {
  const w = Math.sqrt(stiffness), d = from - to;
  if (damping >= 1) return to + d * (1 + w * seconds) * Math.exp(-w * seconds);
  const wd = w * Math.sqrt(1 - damping * damping);
  return to + d * Math.exp(-damping * w * seconds) * (Math.cos(wd * seconds) + damping * w / wd * Math.sin(wd * seconds));
}
