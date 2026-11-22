// The whole library as a song list, shared by Canciones and Buscar («Añadidas recientemente»).
// It is one paginated pass over the library, so a recent answer is reused instead of repeating it.
import {library} from './api.js';

const PAGE = 500;
let cache = null, at = 0, pending = null;

export async function librarySongs(maxAge = 60000) {
  if (cache && Date.now() - at < maxAge) return cache;
  if (pending) return pending;
  pending = (async () => {
    const all = [];
    for (let offset = 0; ; offset += PAGE) {
      const r = await library('search3', {query: ' ', songCount: PAGE, songOffset: offset, artistCount: 0, albumCount: 0});
      const batch = r.searchResult3?.song || [];
      all.push(...batch);
      if (batch.length < PAGE) break;
    }
    cache = all; at = Date.now();
    return all;
  })().finally(() => { pending = null; });
  return pending;
}

export const newestFirst = (a, b) => String(b.created || '').localeCompare(String(a.created || ''));

/** The 20 songs added to the library most recently, as in the app's Buscar. */
export const recentlyAdded = songs => [...songs].sort(newestFirst).slice(0, 20);
