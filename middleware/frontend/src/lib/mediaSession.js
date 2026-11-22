// Lock-screen, notification and headset controls for the web player (Media Session API).
// Without it a phone's browser shows a nameless audio tab and the headset buttons do nothing.

/** What the system shows for a track; null when nothing is loaded. */
export function mediaMetadata(track, artUrl) {
  if (!track) return null;
  return {
    title: track.title || '',
    artist: track.artist || '',
    album: track.album || '',
    artwork: artUrl ? [{src: artUrl, sizes: '512x512'}] : [],
  };
}

/** A position the system accepts: finite, inside the duration. Null when the duration is unknown. */
export function positionState(duration, position, rate = 1) {
  if (!Number.isFinite(duration) || duration <= 0) return null;
  const at = Number.isFinite(position) ? Math.min(Math.max(position, 0), duration) : 0;
  return {duration, position: at, playbackRate: rate > 0 ? rate : 1};
}

/**
 * Wires the player's own actions to the system controls. Returns no-ops where the browser has
 * no Media Session, so callers never have to check.
 */
export function connectMediaSession(nav, Metadata, actions) {
  const session = nav?.mediaSession;
  if (!session) return {update() {}, playing() {}, position() {}};
  const on = (name, handler) => { try { session.setActionHandler(name, handler); } catch { /* action not supported here */ } };
  on('play', actions.play);
  on('pause', actions.pause);
  on('nexttrack', actions.next);
  on('previoustrack', actions.prev);
  on('seekto', event => { if (typeof event?.seekTime === 'number') actions.seekTo(event.seekTime); });
  return {
    update(meta) { session.metadata = meta && Metadata ? new Metadata(meta) : null; },
    playing(isPlaying) { session.playbackState = isPlaying ? 'playing' : 'paused'; },
    position(duration, position, rate) {
      const state = positionState(duration, position, rate);
      if (state && session.setPositionState) { try { session.setPositionState(state); } catch { /* stale values */ } }
    },
  };
}
