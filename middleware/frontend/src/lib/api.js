import { mobile } from './native.js';
const KEY_SESSION = "armonia.session";
let currentSession;

export function getSession() {
  // A tab keeps its identity until explicit login/logout or reload. A cookie
  // changed by another tab must not authorize this tab's stale UI as that user.
  if (currentSession !== undefined) return currentSession;
  try {
    const saved = JSON.parse(localStorage.getItem(KEY_SESSION));
    // Older clients persisted a bearer. Force a fresh cookie login on upgrade.
    if (saved?.sessionId) { localStorage.removeItem(KEY_SESSION); currentSession=null; return null; }
    currentSession=saved || null;
    return currentSession;
  } catch {
    return null;
  }
}

export function setSession(s) {
  currentSession=s ? { username:s.username, userId:s.userId } : null;
  if (mobile) return;
  if (s) {
    localStorage.setItem(KEY_SESSION, JSON.stringify({ username: s.username, userId: s.userId }));
  } else {
    localStorage.removeItem(KEY_SESSION);
  }
}

export async function call(path, opts = {}) {
  const owner=getSession()?.userId;
  const headers = { ...(owner ? {"X-Music-Owner":owner} : {}), ...(opts.headers || {}), "X-Music-Client": "web" };
  if (opts.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  let res;
  try {
    if (mobile) {
      if (opts.body != null && typeof opts.body !== 'string') throw new Error('Formato de carga no compatible');
      const result = await mobile.request({path, method: opts.method || 'GET', body: opts.body,
        albumGroups: headers['X-Armonia-Albums'] === '1'});
      res = new Response(result.text || null, {status: result.status});
    } else res = await fetch(path, { ...opts, headers, credentials: 'same-origin' });
  }
  catch (e) { if(opts.signal?.aborted)throw e;throw new Error('No se pudo conectar. Comprueba la red y vuelve a intentarlo.'); }
  const text = await res.text();
  if (!res.ok) {
    const messages={400:'Revisa los datos e intentalo de nuevo.',401:'Tu sesion ha caducado. Inicia sesion de nuevo.',403:'No tienes permiso para esta operacion o fuente.',404:'Este elemento ya no esta disponible.',409:'Los datos cambiaron en otro dispositivo. Actualiza antes de continuar.',429:'Hay demasiadas operaciones en curso. Espera un momento.'};
    const error=new Error(messages[res.status]||'El servicio no esta disponible. Conservamos tu progreso; vuelve a intentarlo.');
    error.status=res.status;
    try { error.detail=JSON.parse(text).detail; } catch { /* Plain upstream error. */ }
    throw error;
  }
  return text ? JSON.parse(text) : null;
}

function unwrap(r) {
  const sr = r?.["subsonic-response"];
  if (!sr) throw new Error("not a subsonic response");
  if (sr.status !== "ok") {
    throw new Error(`subsonic ${sr.error?.code}: ${sr.error?.message}`);
  }
  return sr;
}

async function authCall(path, opts={}) {
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),30000);
  try {return await call(path,{...opts,signal:controller.signal});}
  finally {clearTimeout(timer);}
}

export const login = (username, password) =>
  authCall("/api/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });

export const logout = () => mobile ? mobile.logout() : authCall("/api/logout", { method: "POST" });

export const me = () => authCall("/api/me");

// Returns { songs: [...], artists: [...] }
export const search = (query, limit = 10, source = "youtube_music", signal = undefined, scope = "all") =>
  call("/api/search", {
    method: "POST",
    body: JSON.stringify({ query, limit, source, scope }),
    signal,
  });

export async function download(videoId, artist, title, source = "youtube_music", album = "", force = false) {
  const job = await call("/api/download", {
    method: "POST",
    body: JSON.stringify({ videoId, artist, title, source, album, force }),
  });
  if (mobile && job.jobId) await mobile.trackDownload({videoId,title,jobId:job.jobId});
  return job;
}

export const searchArtists = (query, limit = 10) =>
  call("/api/search/artists", {
    method: "POST",
    body: JSON.stringify({ query, limit }),
  });

export const getArtist = (channelId) =>
  call(`/api/artist/${encodeURIComponent(channelId)}`);

export const getArtistSongs = (channelId) =>
  call(`/api/artist/${encodeURIComponent(channelId)}/songs`);

export const getAlbum = (browseId) =>
  call(`/api/album/${encodeURIComponent(browseId)}`);

export const status = (jobId) =>
  call(`/api/status/${encodeURIComponent(jobId)}`);

export const rescan = () => call("/api/rescan", { method: "POST" });

export async function library(subpath, params = {}, opts = {}) {
  const qs = Object.entries(params)
    .flatMap(([k, v]) =>
      Array.isArray(v) ? v.map((vi) => [k, String(vi)]) : [[k, String(v)]],
    )
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join("&");
  const r = await call(`/api/library/${subpath}${qs ? "?" + qs : ""}`, opts);
  return unwrap(r);
}

export const deleteTrack = (trackId) =>
  call(`/api/track/${encodeURIComponent(trackId)}`, { method: "DELETE" });

export const listDownloads = () => call("/api/downloads");

export const deleteDownload = (jobId) =>
  call(`/api/downloads/${encodeURIComponent(jobId)}`, { method: "DELETE" });

export const cancelJob = (jobId) =>
  call(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });

export const retryDownload = (jobId) =>
  call(`/api/downloads/${encodeURIComponent(jobId)}/retry`, { method: "POST" });

export const getStats = () => call("/api/stats");

export const importSpotify = (url) =>
  call("/api/import/spotify", {
    method: "POST",
    body: JSON.stringify({ url }),
  });

export const importStatus = (importId) =>
  call(`/api/import/${encodeURIComponent(importId)}`);

export function streamUrl(trackId) {
  return `/api/stream/${encodeURIComponent(trackId)}`;
}

export function previewUrl(videoId) {
  return `/api/preview/${encodeURIComponent(videoId)}`;
}

// Phone covers: drawn size in device pixels, rounded up to a few fixed sizes so one download serves every
// screen (the phone keeps each cover URL), and never below what the Kotlin screen asks for there (128 in
// playlists, the queue and the mini player; 300 in Biblioteca, Buscar and Sin conexion). Desktop: unchanged.
const PHONE_ART = [128, 192, 300, 512, 1024];
export function phoneArtSize(cssPx, dpr, least = 128) {
  const want = Math.max(least, cssPx * (dpr || 1));
  return PHONE_ART.find(size => size >= want) ?? PHONE_ART[PHONE_ART.length - 1];
}
export const artSize = (cssPx, desktop, least = 128) =>
  mobile ? phoneArtSize(cssPx, globalThis.devicePixelRatio, least) : desktop;

export function coverArtUrl(coverArtId, size = 300) {
  if (!coverArtId) return "";
  if (mobile && /^https?:\/\//i.test(coverArtId)) return coverArtId;
  const qs = new URLSearchParams({
    id: coverArtId,
    size: String(size),
  });
  return `/api/library/getCoverArt?${qs}`;
}
