import test from 'node:test';
import assert from 'node:assert/strict';
import {decodeCopies, encodeCopies, withCopy, withoutCopy, saveTarget, exactCopy, COPIES_LIMIT} from '../src/lib/previewCopies.js';

test('copies belong to one account and survive encoding', () => {
  const copies = withCopy(new Map(), 'vid1', 'song-1');
  const raw = encodeCopies(copies, 'ana');
  assert.equal(decodeCopies(raw, 'ana').get('vid1'), 'song-1');
  assert.equal(decodeCopies(raw, 'otra').size, 0, 'another account sees nothing');
});

test('only the newest 500 are kept, and a copy can be forgotten', () => {
  let copies = new Map();
  for (let i = 0; i <= COPIES_LIMIT; i++) copies = withCopy(copies, `v${i}`, `s${i}`);
  assert.equal(copies.size, COPIES_LIMIT);
  assert.equal(copies.has('v0'), false);
  copies = withCopy(copies, 'v1', 's1');          // used again: becomes the newest
  copies = withCopy(copies, 'nuevo', 'x');
  assert.equal(copies.has('v1'), true);
  assert.equal(withoutCopy(copies, 'v1').has('v1'), false);
});

test('damaged text or entries are ignored', () => {
  assert.equal(decodeCopies('{basura', 'ana').size, 0);
  assert.equal(decodeCopies(null, 'ana').size, 0);
  const raw = JSON.stringify({account: 'ana', entries: [['a', 'ok'], ['b', 'preview|x'], [1, 'x'], 'c', ['', 'y']]});
  assert.deepEqual([...decodeCopies(raw, 'ana')], [['a', 'ok']]);
});

test('what can be saved: library songs, YouTube previews, not other providers', () => {
  assert.deepEqual(saveTarget({id: 'abc'}), {kind: 'library', id: 'abc'});
  assert.deepEqual(saveTarget({id: 'youtube|v%2F', _previewUrl: '/api/preview/v%2F'}), {kind: 'download', videoId: 'v/'});
  assert.deepEqual(saveTarget({id: null, _previewUrl: '/api/preview/xyz'}), {kind: 'download', videoId: 'xyz'});
  assert.equal(saveTarget({id: 'otro|1', _previewUrl: '/api/external/1'}), null);
  assert.equal(saveTarget({id: 'otro|1'}), null);
  assert.equal(saveTarget(null), null);
});

test('the downloaded copy must be a single exact match', () => {
  const track = {title: 'Mapa', artist: 'Lúa Norte', duration: 200};
  assert.equal(exactCopy([{id: 1, title: 'mapa', artist: 'LÚA NORTE', duration: 202}, {id: 2, title: 'Mapa (live)', artist: 'Lúa Norte', duration: 200}], track), 1);
  assert.equal(exactCopy([{id: 1, title: 'Mapa', artist: 'Lúa Norte', duration: 210}], track), null, 'too long');
  assert.equal(exactCopy([{id: 1, title: 'Mapa', artist: 'Lúa Norte', duration: 200}, {id: 3, title: 'Mapa', artist: 'Lúa Norte', duration: 199}], track), null, 'two recordings');
});
