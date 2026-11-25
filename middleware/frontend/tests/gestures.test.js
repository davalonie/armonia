import {test} from 'node:test';
import assert from 'node:assert/strict';
import {shouldDismiss, springOffset, velocityOf, DISMISS} from '../src/lib/pullDismiss.js';
import {visibleQueueRows, dropPosition, stepAside} from '../src/lib/queueRows.js';
import {removes} from '../src/lib/swipeRow.js';

test('the expanded player closes like PlayerPane: past 120 dp or flung past 1600 physical px/s', () => {
  assert.equal(shouldDismiss(DISMISS, 0, 2), false);
  assert.equal(shouldDismiss(121, 0, 2), true);
  // 1600 px/s are physical pixels: 800 CSS px/s at a density of 2, 569 at 2.81.
  assert.equal(shouldDismiss(30, 800, 2), false);
  assert.equal(shouldDismiss(30, 801, 2), true);
  assert.equal(shouldDismiss(30, 570, 2.81), true);
  assert.equal(shouldDismiss(30, -5000, 2), false);
});

test('the way back is Compose spring(1, 1500): no overshoot, almost home in 300 ms', () => {
  assert.equal(springOffset(100, 0), 100);
  let previous = 100;
  for (let t = .01; t < .5; t += .01) {
    const x = springOffset(100, t);
    assert.ok(x >= 0 && x < previous);
    previous = x;
  }
  assert.ok(springOffset(100, .3) < 1);
});

test('velocity uses the last samples', () => {
  assert.equal(velocityOf([{y: 0, t: 0}, {y: 50, t: 50}]), 1000);
  assert.equal(velocityOf([{y: 0, t: 0}]), 0);
});

test('queue rows start at the current song, in play order, with keys for repeated songs', () => {
  assert.deepEqual(visibleQueueRows(['a', 'b', 'a', 'c'], [0, 1, 2, 3], 1),
    [{index: 1, key: '0:b'}, {index: 2, key: '1:a'}, {index: 3, key: '0:c'}]);
  assert.deepEqual(visibleQueueRows(['a', 'b', 'c'], [2, 0, 1], 0).map(r => r.index), [0, 1]);
});

test('a dragged row lands past half a neighbour and the others step aside', () => {
  assert.equal(dropPosition(1, 29, 60, 5), 1);
  assert.equal(dropPosition(1, 31, 60, 5), 2);
  assert.equal(dropPosition(1, -1000, 60, 5), 0);
  assert.equal(dropPosition(1, 1000, 60, 5), 4);
  assert.deepEqual([0, 1, 2, 3, 4].map(p => stepAside(p, 1, 3, 60)), [0, 0, -60, -60, 0]);
  assert.deepEqual([0, 1, 2, 3, 4].map(p => stepAside(p, 3, 1, 60)), [0, 60, 60, 0, 0]);
});

test('a queue row is removed like SwipeToDismissBox: 56 dp, or 125 dp/s towards that side', () => {
  assert.equal(removes(55, 0), false);
  assert.equal(removes(-56, 0), true);
  assert.equal(removes(20, 200), true);
  assert.equal(removes(20, -200), false);
  assert.equal(removes(80, -200), false);
  assert.equal(removes(0, 500), false);
});

test('phone covers ask for their drawn size, rounded up to fixed sizes, never below Kotlin', async () => {
  const {phoneArtSize, artSize} = await import('../src/lib/api.js');
  assert.equal(phoneArtSize(52, 2.81), 192);          // the user's phone: 146 px → 192 (it was 64)
  assert.equal(phoneArtSize(52, 1.625), 128);         // the emulator: never below Kotlin's 128
  assert.equal(phoneArtSize(52, 2.81, 300), 300);     // Biblioteca: Kotlin asks 300
  assert.equal(phoneArtSize(220, 2.81), 1024);
  assert.equal(phoneArtSize(5000, 3), 1024);
  assert.equal(artSize(52, 64), 64);                  // desktop: unchanged
});
