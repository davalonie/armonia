import test from 'node:test';
import assert from 'node:assert/strict';
import {withoutDefaultAlbum} from '../src/lib/albums.js';

test('the album of loose songs named by the server is hidden', () => {
  const page = {defaultAlbum: 'Singles', album: [{name: 'Singles'}, {name: 'Mapa'}, {name: 'Singles (Live)'}]};
  assert.deepEqual(withoutDefaultAlbum(page).map(a => a.name), ['Mapa', 'Singles (Live)']);
});

test('without the server mark nothing is hidden, and an empty page is empty', () => {
  assert.deepEqual(withoutDefaultAlbum({album: [{name: 'Singles'}]}).map(a => a.name), ['Singles']);
  assert.deepEqual(withoutDefaultAlbum(undefined), []);
});
