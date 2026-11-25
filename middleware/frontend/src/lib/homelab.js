import { call, getSession, coverArtUrl } from './api.js';

export const api = {
  sources: () => call('/api/sources'),
  discover: () => call('/api/discover'),
  refreshDiscover: (name=null) => call('/api/discover/refresh',{method:'POST',body:JSON.stringify({name})}),
  flows: () => call('/api/discover/flows'),
  flow: id => call(`/api/discover/flows/${encodeURIComponent(id)}`),
  weekly: () => call('/api/discover/weekly', {method:'POST'}),
  refreshFlow: id => call(`/api/discover/flows/${encodeURIComponent(id)}/refresh`, {method:'POST'}),
  history: () => call('/api/discover/history'),
  match: track => call('/api/discover/match', {method:'POST', body:JSON.stringify(track)}),
  link: (username,password) => call('/api/integrations/aurral', {method:'POST',body:JSON.stringify({username,password})}),
  unlink: () => call('/api/integrations/aurral', {method:'DELETE'}),
  aurralStatus: () => call('/api/integrations/aurral'),
  playlists: () => call('/api/mixed-playlists'),
  playlist: id => call(`/api/mixed-playlists/${encodeURIComponent(id)}`),
  save: p => call('/api/mixed-playlists' + (p.id ? `/${p.id}` : ''), {
    method:p.id?'PUT':'POST', body:JSON.stringify({name:p.name,revision:p.revision,items:p.items})}),
  remove: p => call(`/api/mixed-playlists/${p.id}?revision=${p.revision}`, {method:'DELETE'}),
  export: p => call(`/api/mixed-playlists/${p.id}/export-navidrome`, {method:'POST',body:JSON.stringify({revision:p.revision})}),
  top: (kind='artists', period='month') => call(`/api/listening/top/${kind}?period=${period}`),
  capabilities: t => call(`/api/sources/${t.source}/${t.source_id}/capabilities`),
  saveSource: t => call(`/api/sources/${t.source_id}/save`,{method:"POST"}),
  delivery: () => call('/api/listening/status'),
  recent: () => call('/api/recent-playlists'),
  homePlaylists: () => call('/api/home/playlists'),
  homePlaylist: key => call(`/api/home/playlists/${encodeURIComponent(key)}`),
  homeArtists: () => call('/api/home/artists'),
  refreshHome: () => call('/api/home/playlists/refresh', {method:'POST'}),
  activateWeekly: () => call('/api/home/weekly', {method:'POST'}),
  saveGenerated: key => call(`/api/home/playlists/${encodeURIComponent(key)}/save`, {method:'POST'}),
};

// The phone's bridge reads this reference into a Kotlin MusicTrack: every field it declares
// with a default must be present, never undefined (artist_mbids missing closed the app).
export function trackRef(track) {
  return {...track, album:track.album || '', duration:track.duration > 0 ? track.duration : null,
    recording_mbid:track.recording_mbid || null, isrc:track.isrc || null,
    artist_mbids:Array.isArray(track.artist_mbids) ? track.artist_mbids : []};
}

// Stable references use the existing queue/audio element, never provider URLs.
export function toQueueTrack(track, cover=null) {
  track = trackRef(track);
  return { id: track.source === 'navidrome' ? track.source_id : `${track.source}|${track.source_id}`,
    title:track.title, artist:track.artist, album:track.album, duration:track.duration,
    _musicTrack:track,
    ...(track.source === 'navidrome' ? {coverArt:track.source_id} : {_previewThumb:artUrl({...track,cover}), _previewUrl:track.source === 'youtube'
      ? `/api/preview/${encodeURIComponent(track.source_id)}` : `/api/external/${encodeURIComponent(track.source_id)}`}) };
}

// Artwork for a stored track reference: library art by id, the thumbnail saved
// with a generated item, or the public video still. Never a provider audio URL.
export function artUrl(ref, size=300) {
  if (!ref) return '';
  if (typeof ref === 'string') return ref;
  if (ref.cover) return ref.cover;
  if (ref.source === 'navidrome') return coverArtUrl(ref.source_id, size);
  if (ref.source === 'youtube') return `https://i.ytimg.com/vi/${encodeURIComponent(ref.source_id)}/mqdefault.jpg`;
  return '';
}

export function fromQueueTrack(song) {
  if (song._musicTrack) return song._musicTrack;
  const preview = song._previewUrl?.match(/^\/api\/preview\/([\w-]+)$/);
  return {source:preview?'youtube':'navidrome', source_id:preview?preview[1]:song.id,
    title:song.title || 'Unknown', artist:song.artist || 'Unknown', album:song.album || '',
    duration:song.duration > 0 ? song.duration : null,
    recording_mbid:validMbid(song.musicBrainzId)?song.musicBrainzId:null,
    artist_mbids:(song.artists||[]).map(a=>a.musicBrainzId).filter(validMbid).slice(0,20),
    isrc:(song.isrc||[]).find(value=>/^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$/.test(value))||null};
}
const validMbid=value=>typeof value==='string'&&/^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(value);

export const accountKey = () => getSession()?.userId || null;
