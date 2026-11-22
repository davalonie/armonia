import test from 'node:test';
import assert from 'node:assert/strict';
import {mediaMetadata, positionState, connectMediaSession} from '../src/lib/mediaSession.js';

test('the system is told the title, artists, album and cover of the song', () => {
  assert.deepEqual(mediaMetadata({title: 'Bajamar', artist: 'Lúa Norte, Faro Sur', album: 'Mareas'}, '/cover?id=1'),
    {title: 'Bajamar', artist: 'Lúa Norte, Faro Sur', album: 'Mareas', artwork: [{src: '/cover?id=1', sizes: '512x512'}]});
  assert.deepEqual(mediaMetadata({title: 'Sin portada'}, ''), {title: 'Sin portada', artist: '', album: '', artwork: []});
  assert.equal(mediaMetadata(null, ''), null);
});

test('a position is only reported with a known duration and never outside it', () => {
  assert.equal(positionState(NaN, 3), null);
  assert.equal(positionState(0, 3), null);
  assert.deepEqual(positionState(200, 250), {duration: 200, position: 200, playbackRate: 1});
  assert.deepEqual(positionState(200, -5, 0), {duration: 200, position: 0, playbackRate: 1});
});

test('headset and lock-screen buttons run the player actions', () => {
  const handlers = {}, calls = [];
  const session = {setActionHandler: (name, handler) => { handlers[name] = handler; }, setPositionState: state => calls.push(['position', state])};
  class Metadata { constructor(init) { Object.assign(this, init); } }
  const media = connectMediaSession({mediaSession: session}, Metadata, {
    play: () => calls.push('play'), pause: () => calls.push('pause'), next: () => calls.push('next'),
    prev: () => calls.push('prev'), seekTo: seconds => calls.push(['seek', seconds]),
  });
  handlers.play(); handlers.pause(); handlers.nexttrack(); handlers.previoustrack(); handlers.seekto({seekTime: 42}); handlers.seekto({});
  assert.deepEqual(calls, ['play', 'pause', 'next', 'prev', ['seek', 42]]);
  media.update(mediaMetadata({title: 'Bajamar', artist: 'Lúa Norte'}, ''));
  assert.equal(session.metadata.title, 'Bajamar');
  media.playing(true); assert.equal(session.playbackState, 'playing');
  media.playing(false); assert.equal(session.playbackState, 'paused');
  media.position(200, 10); assert.deepEqual(calls.at(-1), ['position', {duration: 200, position: 10, playbackRate: 1}]);
  media.update(null); assert.equal(session.metadata, null);
});

test('a browser without Media Session, or one that rejects an action, does not break the player', () => {
  const none = connectMediaSession({}, undefined, {});
  none.update({title: 'x'}); none.playing(true); none.position(10, 1);
  const picky = {setActionHandler: name => { if (name === 'seekto') throw new Error('unsupported'); }};
  assert.doesNotThrow(() => connectMediaSession({mediaSession: picky}, undefined, {play() {}, pause() {}, next() {}, prev() {}, seekTo() {}}));
});
