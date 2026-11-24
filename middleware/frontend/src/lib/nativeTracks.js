import {toQueueTrack} from './homelab.js';

// Older MediaSession items can have the native media ID without the structured source reference.
export function nativeTrack(song, snapshot, automatic) {
  const legacy=/^(preview|external)\|(.+)$/.exec(song.id);
  const ref=song.musicTrack || (legacy && {
    source:legacy[1]==='preview'?'youtube':'authorized_http',source_id:legacy[2],
    title:song.title,artist:song.artist,album:song.album,duration:song.duration,
  });
  const external=ref && ref.source!=='navidrome' ? toQueueTrack(ref) : {};
  let thumb=song.coverArt || external._previewThumb;
  if (external._previewUrl && thumb && /^https?:\/\//i.test(thumb)) {
    try {
      const url=new URL(thumb);
      if (url.searchParams.has('account') && /^\/api\/home\/releases\/[a-f0-9-]{36}\/cover$/.test(url.pathname)) thumb=url.pathname;
    } catch { /* An invalid thumbnail can still use the normal image fallback. */ }
  }
  return {...external,...song,_musicTrack:ref,_previewThumb:thumb,
    _auto:automatic.has(song.id), _from:snapshot.from,
    _playlist:snapshot.playlist?{kind:snapshot.playlistKind||'local',id:snapshot.playlist}:null};
}
