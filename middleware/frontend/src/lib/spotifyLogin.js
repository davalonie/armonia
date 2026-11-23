// The owner's own Spotify sign-in, entirely in this browser (authorization code + PKCE):
// no client secret exists, the password is typed on Spotify's page, and the short-lived
// access token stays in memory and is never sent to the Armonia server.
const AUTHORIZE = 'https://accounts.spotify.com/authorize';
const TOKEN = 'https://accounts.spotify.com/api/token';
const API = 'https://api.spotify.com/v1';
const SCOPES = 'playlist-read-private playlist-read-collaborative user-library-read';
const PENDING = 'armonia.spotify-login';
export const PLAYLIST_LIMIT = 5000;  // the server's limit for one imported playlist

const base64url = bytes => btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

export function redirectUri(location = globalThis.location) {
  return `${location.origin}/`;
}

export function hasPendingLogin(storage = globalThis.sessionStorage) {
  try { return !!storage.getItem(PENDING); } catch { return false; }
}

/** Remembers the verifier for this tab and returns Spotify's sign-in address to navigate to. */
export async function beginLogin(clientId, {location = globalThis.location, storage = globalThis.sessionStorage, crypto = globalThis.crypto} = {}) {
  if (!/^[0-9a-f]{32}$/.test(clientId || '')) throw new Error('El identificador de la aplicacion de Spotify no es valido.');
  const verifier = base64url(crypto.getRandomValues(new Uint8Array(64)));
  const state = base64url(crypto.getRandomValues(new Uint8Array(16)));
  const challenge = base64url(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))));
  storage.setItem(PENDING, JSON.stringify({clientId, verifier, state}));
  const query = new URLSearchParams({
    client_id: clientId, response_type: 'code', redirect_uri: redirectUri(location), scope: SCOPES,
    code_challenge_method: 'S256', code_challenge: challenge, state,
  });
  return `${AUTHORIZE}?${query}`;
}

/**
 * Finishes a sign-in after Spotify returned to this page. Resolves to an access token, or
 * null when this page load is not a return from Spotify. The pending verifier is single use.
 */
export async function completeLogin({search = globalThis.location.search, location = globalThis.location, storage = globalThis.sessionStorage, fetch = globalThis.fetch} = {}) {
  const params = new URLSearchParams(search);
  if (!params.has('code') && !params.has('error')) return null;
  let pending = null;
  try { pending = JSON.parse(storage.getItem(PENDING)); } catch { /* Treated as no sign-in in progress. */ }
  storage.removeItem(PENDING);
  if (!pending) return null;
  if (params.get('state') !== pending.state) throw new Error('La respuesta de Spotify no corresponde a este inicio de sesion. Vuelve a intentarlo.');
  if (params.has('error')) throw new Error(params.get('error') === 'access_denied' ? 'No has dado permiso en Spotify.' : 'Spotify no completo el inicio de sesion.');
  const response = await fetch(TOKEN, {
    method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: new URLSearchParams({
      grant_type: 'authorization_code', code: params.get('code'), redirect_uri: redirectUri(location),
      client_id: pending.clientId, code_verifier: pending.verifier,
    }),
  });
  if (!response.ok) throw new Error('Spotify rechazo el inicio de sesion. Comprueba el identificador y la direccion de retorno de tu aplicacion.');
  const token = (await response.json()).access_token;
  if (!token) throw new Error('Spotify no entrego acceso.');
  return token;
}

function failure(status) {
  const messages = {
    401: 'El acceso de Spotify ha caducado. Vuelve a conectar.',
    403: 'Spotify no permite el acceso a esta aplicacion: su dueño necesita Premium activo y tu cuenta debe estar autorizada en ella.',
    429: 'Spotify esta limitando las peticiones. Espera unos minutos y vuelve a intentarlo.',
  };
  const error = new Error(messages[status] || 'Spotify no esta disponible ahora. Vuelve a intentarlo.');
  error.status = status;
  return error;
}

async function get(url, token, {fetch, wait}) {
  for (let attempt = 0; ; attempt++) {
    const response = await fetch(url, {headers: {Authorization: `Bearer ${token}`}});
    if (response.ok) return response.json();
    if (response.status === 429 && attempt < 5) {
      const seconds = Number(response.headers?.get?.('Retry-After'));
      await wait(Math.min(30, Number.isFinite(seconds) && seconds > 0 ? seconds : 2) * 1000);
      continue;
    }
    throw failure(response.status);
  }
}

async function pages(url, token, io, each) {
  // `next` is Spotify's own address for the following page; never follow one that leaves its API.
  for (let next = url, guard = 0; next && guard < 400; guard++) {
    if (!next.startsWith(`${API}/`)) throw failure(0);
    const page = await get(next, token, io);
    (page.items || []).forEach(each);
    next = page.next;
  }
}

/** One source row in the shape the server's import expects. A missing title stays as an unavailable position. */
export function toTrack(item, album = null) {
  if (!item || (item.type && item.type !== 'track')) return {title: '', artist: '', album: '', duration: null, isrc: null, sourceId: null};
  return {
    title: (item.name || '').slice(0, 300),
    artist: (item.artists || []).map(a => a?.name).filter(Boolean).join(', ').slice(0, 600),
    // One by one as well: once joined, a name with a comma looks like two performers.
    artists: (item.artists || []).map(a => a?.name).filter(Boolean).slice(0, 40).map(n => n.slice(0, 300)),
    albumArtist: ((album || item.album)?.artists || []).map(a => a?.name).filter(Boolean).join(', ').slice(0, 600),
    album: ((album || item.album)?.name || '').slice(0, 300),
    trackNumber: Number.isInteger(item.track_number) && item.track_number > 0 ? item.track_number : null,
    discNumber: Number.isInteger(item.disc_number) && item.disc_number > 0 ? item.disc_number : null,
    releaseDate: /^\d{4}(-\d{2}(-\d{2})?)?$/.test((album || item.album)?.release_date || '') ? (album || item.album).release_date : null,
    duration: item.duration_ms > 0 ? item.duration_ms / 1000 : null,
    isrc: item.external_ids?.isrc || null,
    sourceId: item.uri ? String(item.uri).slice(0, 128) : null,
  };
}

function chunks(name, tracks) {
  if (tracks.length <= PLAYLIST_LIMIT) return [{name, tracks}];
  const parts = [];
  for (let i = 0; i < tracks.length; i += PLAYLIST_LIMIT) parts.push({name: `${name} (${parts.length + 1})`, tracks: tracks.slice(i, i + PLAYLIST_LIMIT)});
  return parts;
}

/**
 * Everything this sign-in can read: saved songs, saved albums and the playlists the user
 * owns or collaborates on. Spotify gives applications in development mode only the names of
 * other people's playlists; those are returned in `unreadable` instead of being guessed.
 */
export async function readLibrary(token, {fetch = globalThis.fetch, wait = ms => new Promise(r => setTimeout(r, ms)), onProgress = () => {}} = {}) {
  const io = {fetch, wait};
  const me = await get(`${API}/me`, token, io);
  const playlists = [], unreadable = [];

  onProgress('Canciones que te gustan');
  const liked = [];
  await pages(`${API}/me/tracks?limit=50`, token, io, entry => liked.push(toTrack(entry.track)));
  if (liked.length) playlists.push(...chunks('Canciones que te gustan', liked));

  onProgress('Albumes guardados');
  const albums = [];
  await pages(`${API}/me/albums?limit=50`, token, io, entry => albums.push(entry.album));
  const albumTracks = [];
  for (const album of albums.filter(Boolean)) {
    (album.tracks?.items || []).forEach(t => albumTracks.push(toTrack({...t, type: 'track'}, album)));
    if (album.tracks?.next) await pages(album.tracks.next, token, io, t => albumTracks.push(toTrack({...t, type: 'track'}, album)));
  }
  if (albumTracks.length) playlists.push(...chunks('Albumes guardados', albumTracks));

  const listed = [];
  await pages(`${API}/me/playlists?limit=50`, token, io, p => { if (p) listed.push(p); });
  for (const playlist of listed) {
    const name = (playlist.name || 'Playlist sin nombre').slice(0, 150);
    if (playlist.owner?.id !== me.id && !playlist.collaborative) {
      unreadable.push({name, owner: playlist.owner?.display_name || playlist.owner?.id || '', total: (playlist.items || playlist.tracks)?.total ?? null});
      continue;
    }
    onProgress(name);
    const tracks = [];
    try {
      await pages(`${API}/playlists/${encodeURIComponent(playlist.id)}/items?limit=50`, token, io, entry => tracks.push(toTrack(entry.item || entry.track)));
    } catch (error) {
      if (error.status !== 403 && error.status !== 404) throw error;
      unreadable.push({name, owner: playlist.owner?.display_name || '', total: null});
      continue;
    }
    playlists.push(...chunks(name, tracks));
  }
  return {user: me.display_name || me.id || '', playlists, unreadable};
}
