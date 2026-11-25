import {test} from 'node:test';
import assert from 'node:assert/strict';
import {get} from 'svelte/store';
import {createSnackbarHost, springAt, SHORT, LONG, OPACITY, SCALE, HIDDEN_SCALE, SETTLED} from '../src/lib/phoneSnackbar.js';
import {queuedMessage} from '../src/lib/queueNotice.js';

// A clock the test moves by hand.
function clock() {
  let now = 0, timers = [];
  return {
    setTimer: (fn, ms) => { const t = {fn, at: now + ms}; timers.push(t); return t; },
    clearTimer: t => { timers = timers.filter(x => x !== t); },
    advance(ms) { now += ms; for (const t of timers.filter(t => t.at <= now)) { timers = timers.filter(x => x !== t); t.fn(); } },
  };
}

test('one notice at a time, the rest wait their turn in order (SnackbarHostState)', () => {
  const c = clock(), host = createSnackbarHost(c);
  host.show({message: 'uno'}); host.show({message: 'dos', long: true}); host.show({message: 'tres'});
  assert.equal(get(host).message, 'uno');
  c.advance(SHORT - 1); assert.equal(get(host).message, 'uno');
  c.advance(1); assert.equal(get(host).message, 'dos');
  c.advance(LONG - 1); assert.equal(get(host).message, 'dos');
  c.advance(1); assert.equal(get(host).message, 'tres');
  c.advance(SHORT); assert.equal(get(host), null);
});

test('durations: Short 4 s, Long 10 s, as SnackbarDuration.toMillis', () => {
  assert.equal(SHORT, 4000);
  assert.equal(LONG, 10000);
});

test('a newer queue notice takes the place of the one showing, and of one still waiting', () => {
  const c = clock(), host = createSnackbarHost(c);
  host.show({message: '«A» añadida a la cola', replace: 'queue'});
  c.advance(1000);
  host.show({message: '«B» añadida a la cola', replace: 'queue'});
  assert.equal(get(host).message, '«B» añadida a la cola');
  // Its own 4 s, counted from when it shows.
  c.advance(SHORT - 1); assert.equal(get(host).message, '«B» añadida a la cola');
  c.advance(1); assert.equal(get(host), null);
  host.show({message: 'error', long: true});
  host.show({message: '«C» añadida a la cola', replace: 'queue'});
  host.show({message: '«D» añadida a la cola', replace: 'queue'});
  c.advance(LONG);
  assert.equal(get(host).message, '«D» añadida a la cola');
  c.advance(SHORT); assert.equal(get(host), null);
});

test('«Deshacer» runs its action once and the next notice shows', () => {
  const c = clock(), host = createSnackbarHost(c);
  let undone = 0;
  const id = host.show({message: 'x', action: () => undone++});
  host.show({message: 'y'});
  host.act(id); host.act(id);
  assert.equal(undone, 1);
  assert.equal(get(host).message, 'y');
});

test('the queue notices name the song, as MainScreen does', () => {
  assert.equal(queuedMessage('Espuma', 'add'), '«Espuma» añadida a la cola');
  assert.equal(queuedMessage('Espuma', 'end'), '«Espuma» añadida al final de la cola');
  assert.equal(queuedMessage('Espuma', 'next'), '«Espuma» sonara a continuacion');
});

// When a spring that starts at rest is within 0.01 of its target for good.
function settles(from, to, spec) {
  let last = 0;
  for (let ms = 0; ms <= 1000; ms++) if (Math.abs(springAt(from, to, ms / 1000, spec) - to) >= SETTLED) last = ms + 1;
  return last;
}

test('FadeInFadeOutWithScale with the standard motion scheme: in place in about a tenth of a second', () => {
  assert.equal(springAt(0, 1, 0, OPACITY), 0);
  assert.equal(springAt(HIDDEN_SCALE, 1, 0, SCALE), HIDDEN_SCALE);
  const fade = settles(0, 1, OPACITY), grow = settles(HIDDEN_SCALE, 1, SCALE);
  assert.ok(fade > 90 && fade < 130, `opacidad ${fade} ms`);
  assert.ok(grow > 60 && grow < 130, `escala ${grow} ms`);
  // FastEffects has no bounce; FastSpatial overshoots by less than the threshold.
  for (let ms = 0; ms < 400; ms += 5) {
    assert.ok(springAt(0, 1, ms / 1000, OPACITY) <= 1);
    assert.ok(springAt(HIDDEN_SCALE, 1, ms / 1000, SCALE) < 1 + SETTLED);
  }
});
