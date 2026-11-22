import test from 'node:test';
import assert from 'node:assert/strict';
import {releaseDay, releaseLine} from '../src/lib/releases.js';

test('release dates and card line as in the app', () => {
  assert.equal(releaseDay('2026-11-12'), '12 nov');
  assert.equal(releaseDay('2026-01-03'), '3 ene');
  assert.equal(releaseDay(''), '');
  assert.equal(releaseLine({artist: 'Foyone', type: 'Álbum', date: '2026-11-12', upcoming: false}), 'Foyone · Álbum · Nuevo · 12 nov');
  assert.equal(releaseLine({artist: 'Foyone', type: 'Single', date: '2026-12-03', upcoming: true}), 'Foyone · Single · Sale el 3 dic');
});
