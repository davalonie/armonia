import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

// playerStore needs a browser; the pure helper is checked from its source, like other store tests here do.
const source = readFileSync(new URL('../src/lib/stores/playerStore.js', import.meta.url), 'utf8');
const helper = source.match(/export const firstShuffled = (.*);/)[1];
const firstShuffled = eval(helper);

test('with shuffle on, Play starts from a random song inside the list', () => {
  assert.equal(firstShuffled(10, () => 0), 0);
  assert.equal(firstShuffled(10, () => 0.999999), 9);
  assert.equal(firstShuffled(10, () => 1), 9, 'never past the end');
  assert.equal(firstShuffled(1, () => 0.5), 0);
});

test('list headers no longer start shuffled playback: the button is the global switch', () => {
  assert.doesNotMatch(source, /export function playShuffled/);
  assert.match(source, /export function playList\(tracks(, epoch = undefined)?\)/);
});
