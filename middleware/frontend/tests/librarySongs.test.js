import test from 'node:test';
import assert from 'node:assert/strict';
import {recentlyAdded} from '../src/lib/librarySongs.js';

test('Añadidas recientemente: the 20 newest songs, newest first', () => {
  const songs = Array.from({length: 30}, (_, i) => ({id: String(i), created: `2026-11-${String(i % 28 + 1).padStart(2, '0')}T10:00:00Z`}));
  const recent = recentlyAdded(songs);
  assert.equal(recent.length, 20);
  assert.equal(recent[0].created, '2026-11-28T10:00:00Z');
  assert.ok(recent.every((s, i) => i === 0 || recent[i - 1].created >= s.created));
  assert.equal(songs[0].id, '0', 'the library list is not reordered');
  assert.deepEqual(recentlyAdded([]), []);
});
