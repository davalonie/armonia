import test from 'node:test';
import assert from 'node:assert/strict';
import {listenTime, chartDate, whenHeard} from '../src/lib/listening.js';

test('listening time in minutes, then hours and minutes', () => {
  assert.equal(listenTime(59), '0 min');
  assert.equal(listenTime(45 * 60 + 30), '45 min');
  assert.equal(listenTime(3 * 3600 + 12 * 60), '3 h 12 min');
  assert.equal(listenTime(null), '0 min');
});

test('chart dates as in the app for each period', () => {
  assert.equal(chartDate('2026-10-21', 'week'), '21 oct');
  assert.equal(chartDate('2026-10-21', 'month'), '21 oct');
  assert.equal(chartDate('2025-11-17', 'year'), '17 nov 2025');
  assert.equal(chartDate('2025-11-01', 'always'), 'nov 2025');
  assert.equal(chartDate(null, 'week'), '');
});

test('when it was heard: today, yesterday or the day', () => {
  const now = new Date(2026, 10, 20, 12, 0);
  assert.equal(whenHeard(new Date(2026, 10, 20, 9, 5).getTime() / 1000, now), 'hoy 09:05');
  assert.equal(whenHeard(new Date(2026, 10, 19, 23, 40).getTime() / 1000, now), 'ayer 23:40');
  assert.equal(whenHeard(new Date(2026, 10, 12, 8, 0).getTime() / 1000, now), '12 nov');
});
