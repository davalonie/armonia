// «Guardar en una playlist» as in the app (AddToPlaylistSheet): Tus favoritos and your library playlists, ticked
// where the song already is; a YouTube preview is downloaded first. The players' + / ✓ asks the server whether the
// song is saved anywhere (GET /api/playlists/membership?summary=true).
import {writable, get} from 'svelte/store';
import {call, library, download, status, getSession} from './api.js';
import {decodeCopies, encodeCopies, withCopy, withoutCopy, saveTarget, exactCopy} from './previewCopies.js';
import {mobile} from './native.js';
import {phoneOnline} from './stores/connection.js';

export {saveTarget};
export const FAVORITES = ':favoritos';
/** The track whose sheet is open, or null. */
export const saveSheet = writable(null);
/** saved[key] = true / false once known; key is the library id or «preview|videoId». */
export const saved = writable({});

const COPIES_KEY = 'armonia:copias';
const account = () => getSession()?.userId || getSession()?.username || '';
function readCopies() { try { return decodeCopies(localStorage.getItem(COPIES_KEY), account()); } catch { return new Map(); } }
function writeCopies(copies) { try { localStorage.setItem(COPIES_KEY, encodeCopies(copies, account())); } catch { /* Only costs a new download. */ } }

const keyOf = target => target.kind === 'library' ? target.id : `preview|${target.videoId}`;
/** The library song behind this target, if there is one. */
export const localCopy = target => !target ? null : target.kind === 'library' ? target.id : readCopies().get(target.videoId) || null;

const asking = new Map();
// On the phone, unanswered questions (no connection yet when the app opens, the server out of reach) are asked
// again after 1, 2, 4, 8 and 16 s, and when the connection comes back, so the ✓ needs no press of play to show up.
const failed = new Map();
const RETRIES = 5;
/** Fills `saved` for the track; repeated calls while one is pending share it. */
export function checkSaved(track, force = false) {
  const target = saveTarget(track);
  if (!target) return;
  const key = keyOf(target);
  if (!force && (key in get(saved) || asking.has(key))) return;
  const local = localCopy(target);
  if (!local) { saved.update(s => ({...s, [key]: false})); return; }
  const pending = call(`/api/playlists/membership?song=${encodeURIComponent(local)}&summary=true`)
    .then(r => { failed.delete(key); saved.update(s => ({...s, [key]: !!r?.saved})); })
    .catch(() => {
      // Unknown for now: the button keeps showing + (and, on the phone, asks again).
      if (!mobile) return;
      const tries = (failed.get(key)?.tries || 0) + 1;
      failed.set(key, {track, tries});
      if (tries <= RETRIES) setTimeout(() => { if (failed.get(key)?.tries === tries) checkSaved(track); }, 1000 * 2 ** (tries - 1));
    })
    .finally(() => asking.delete(key));
  asking.set(key, pending);
}
/** The connection is back: what could not be asked before is asked now. */
export function recheckUnanswered() {
  for (const [key, {track}] of failed) if (!asking.has(key)) checkSaved(track);
}
let wasOnline = true;
phoneOnline.subscribe(online => { if (online && !wasOnline) recheckUnanswered(); wasOnline = online; });

/** A copy deleted from the library since is forgotten, so saving downloads the song again. */
async function stillThere(target, track, local) {
  if (target.kind === 'library') return true;
  try {
    const found = (await library('search3', {query: track.title, songCount: 100, albumCount: 0, artistCount: 0})).searchResult3?.song || [];
    if (found.some(s => s.id === local)) return true;
  } catch { return true; }   // Without an answer, keep it: the server says the truth on save.
  writeCopies(withoutCopy(readCopies(), target.videoId));
  return false;
}

/** Playlists of this account and where the song already is. */
export async function loadSheet(track) {
  const target = saveTarget(track);
  if (!target) throw new Error('Esta cancion no se puede guardar en una playlist');
  const me = getSession()?.username;
  const listing = await library('getPlaylists');
  const playlists = (listing.playlists?.playlist || []).filter(p => p.owner === me);
  let local = localCopy(target);
  if (local && !(await stillThere(target, track, local))) local = null;
  const included = new Set();
  if (local) {
    const m = await call(`/api/playlists/membership?song=${encodeURIComponent(local)}`);
    if (m.favorite) included.add(FAVORITES);
    for (const id of m.playlists || []) included.add(id);
  }
  // The players' + / ✓ follows what the sheet has just seen (for example, a copy deleted since).
  saved.update(st => ({...st, [keyOf(target)]: included.size > 0}));
  return {playlists, included, needsDownload: !local};
}

const wait = ms => new Promise(r => setTimeout(r, ms));
/** Downloads a preview into the library and returns its song id (the app's downloadForPlaylist). */
async function downloadCopy(target, track, onNote) {
  onNote(`Descargando «${track.title}»…`);
  let job = null;
  try { job = (await download(target.videoId, track.artist || '', track.title || '', 'youtube_music', track.album || '')).jobId; }
  catch (e) { if (e.status !== 409) throw new Error('No se pudo iniciar la descarga'); }   // 409: already in the library.
  if (job) {
    const until = Date.now() + 180_000;
    for (;;) {
      const state = (await status(job)).status;
      if (state === 'done') break;
      if (state === 'error' || state === 'cancelled') throw new Error(`No se pudo descargar «${track.title}». No se ha guardado.`);
      if (Date.now() > until) throw new Error('La descarga sigue pendiente. Reintenta al terminar.');
      await wait(1500);
    }
  }
  const found = (await library('search3', {query: track.title, songCount: 100, albumCount: 0, artistCount: 0})).searchResult3?.song || [];
  const id = exactCopy(found, track);
  if (!id) throw new Error('No se pudo identificar una unica grabacion en la biblioteca');
  writeCopies(withCopy(readCopies(), target.videoId, id));
  onNote('');
  return id;
}

/** Applies the ticks that changed. Returns the failures (empty when all went well) and what is now included. */
export async function saveChanges(track, included, selected, onNote = () => {}) {
  const target = saveTarget(track);
  const local = localCopy(target) || await downloadCopy(target, track, onNote);
  const now = new Set(included), failures = [];
  for (const id of new Set([...selected].filter(x => !included.has(x)).concat([...included].filter(x => !selected.has(x))))) {
    const add = selected.has(id);
    try {
      if (id === FAVORITES) await library(add ? 'star' : 'unstar', {id: local});
      else await call(`/api/playlists/${encodeURIComponent(id)}/membership`, {method: 'PUT', body: JSON.stringify({song: local, included: add})});
      if (add) now.add(id); else now.delete(id);
    } catch { failures.push('No se pudo guardar el cambio'); }
  }
  saved.update(s => ({...s, [keyOf(target)]: now.size > 0}));
  return {failures, included: now};
}

export async function createPlaylist(name) {
  await library('createPlaylist', {name});
}
