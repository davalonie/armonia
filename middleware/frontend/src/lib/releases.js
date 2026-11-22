// «Novedades para ti», as in the app: new and upcoming releases of the artists you listen to (/api/home/releases).
import {call, getSession} from './api.js';
import {refRow} from './lists.js';

const MONTHS = 'ene feb mar abr may jun jul ago sep oct nov dic'.split(' ');
/** «12 nov» from «2026-11-12». */
export function releaseDay(iso) {
  const [, m, d] = String(iso || '').split('-').map(Number);
  return m && d && MONTHS[m - 1] ? `${d} ${MONTHS[m - 1]}` : '';
}
/** The card's second line: «Artista · Álbum · Nuevo · 12 nov» or «… · Sale el 3 dic». */
export const releaseLine = r => `${r.artist} · ${r.type} · ${r.upcoming ? `Sale el ${releaseDay(r.date)}` : `Nuevo · ${releaseDay(r.date)}`}`;

export const releaseCover = r => r.hasCover
  ? `/api/home/releases/${encodeURIComponent(r.id)}/cover?account=${encodeURIComponent(getSession()?.userId || '')}` : '';

export const releaseEntry = r => ({type: 'release', id: r.id, title: r.title, description: r.artist, eyebrow: r.type,
  variant: 'plain', covers: releaseCover(r) ? [releaseCover(r)] : [], cover: releaseCover(r)});

export const calendar = () => call('/api/home/releases');

const wait = ms => new Promise(r => setTimeout(r, ms));
/** The release's songs; the server may still be finding them, so it is asked again for up to a minute. */
export async function releaseRows(entry, still = () => true) {
  let response = await call(`/api/home/releases/${encodeURIComponent(entry.id)}`);
  for (let i = 0; response.preparing && i < 24 && still(); i++) {
    await wait(2500);
    response = await call(`/api/home/releases/${encodeURIComponent(entry.id)}`);
  }
  return {rows: response.items.map(item => refRow({track: item.track, cover: item.track.source === 'navidrome' ? undefined : entry.cover || undefined}))};
}
