import test from 'node:test';
import assert from 'node:assert/strict';
import {scrollInitial, scrollMonth, scrollMinutes, songLabels} from '../src/lib/fastScroll.js';

test('initials: accents dropped, Ñ kept, numbers and symbols are #', () => {
  assert.equal(scrollInitial('Árbol'), 'A');
  assert.equal(scrollInitial('écija'), 'E');
  assert.equal(scrollInitial('ñu'), 'Ñ');
  assert.equal(scrollInitial('Ñandú'), 'Ñ');
  assert.equal(scrollInitial('  zeta'), 'Z');
  assert.equal(scrollInitial('2 Minutos'), '#');
  assert.equal(scrollInitial('¿Quién?'), '#');
  assert.equal(scrollInitial(''), '#');
  assert.equal(scrollInitial(null), '#');
});

test('month and year, minutes', () => {
  assert.equal(scrollMonth('2026-11-19T10:00:00Z'), 'nov 2026');
  assert.equal(scrollMonth('2025-01-03'), 'ene 2025');
  assert.equal(scrollMonth(''), '—');
  assert.equal(scrollMonth('basura'), '—');
  assert.equal(scrollMinutes(245), '4 min');
  assert.equal(scrollMinutes(null), '0 min');
});

test('labels follow the current order, and an empty list has none', () => {
  const songs = [{title: 'Ñoño', artist: 'Álvaro', created: '2026-11-01', duration: 61}, {title: '1999', artist: 'Bea', created: '2026-10-02', duration: 300}];
  assert.deepEqual(songLabels(songs, 'title-asc'), ['Ñ', '#']);
  assert.deepEqual(songLabels(songs, 'artist-asc'), ['A', 'B']);
  assert.deepEqual(songLabels(songs, 'added-desc'), ['nov 2026', 'oct 2026']);
  assert.deepEqual(songLabels(songs, 'duration-asc'), ['1 min', '5 min']);
  assert.deepEqual(songLabels(songs, 'original'), ['1', '2']);
  assert.deepEqual(songLabels([], 'title-asc'), []);
});
