// Which library song a YouTube preview became when it was saved («Descargar y guardar»), as the app's PreviewCopies:
// per account, the newest 500, so the player shows ✓ and saving again does not download it twice.
export const COPIES_LIMIT = 500;

/** Parses the stored text for this account; anything damaged or from another account is ignored. */
export function decodeCopies(raw, account) {
  const copies = new Map();
  try {
    const data = JSON.parse(raw || 'null');
    if (!data || data.account !== account || !Array.isArray(data.entries)) return copies;
    for (const entry of data.entries) {
      if (Array.isArray(entry) && typeof entry[0] === 'string' && typeof entry[1] === 'string' && entry[0] && entry[1]
        && !entry[1].includes('|')) copies.set(entry[0], entry[1]);
    }
  } catch { /* A damaged entry only costs a new download. */ }
  return trim(copies);
}

export const encodeCopies = (copies, account) => JSON.stringify({account, entries: [...copies]});

/** Remembers (or refreshes) a copy as the newest one. */
export function withCopy(copies, preview, local) {
  const next = new Map(copies);
  next.delete(preview);
  next.set(preview, local);
  return trim(next);
}

export function withoutCopy(copies, preview) {
  const next = new Map(copies);
  next.delete(preview);
  return next;
}

function trim(copies) {
  while (copies.size > COPIES_LIMIT) copies.delete(copies.keys().next().value);
  return copies;
}

/**
 * What saving this track means: a library song is saved as it is; a YouTube preview is downloaded first; anything
 * else (a song from another provider, nothing playing) cannot go into a library playlist.
 */
export function saveTarget(track) {
  if (!track) return null;
  if (!track._previewUrl) return track.id && !String(track.id).includes('|') ? {kind: 'library', id: track.id} : null;
  const match = /^\/api\/preview\/([^/?#]+)$/.exec(track._previewUrl);
  return match ? {kind: 'download', videoId: decodeURIComponent(match[1])} : null;
}

/** The one library song that is this download: same title and artist, and length within 3 s when known. */
export function exactCopy(found, track) {
  const same = (a, b) => String(a || '').toLocaleLowerCase('es') === String(b || '').toLocaleLowerCase('es');
  const matches = (found || []).filter(s => same(s.title, track.title) && same(s.artist, track.artist)
    && (!track.duration || Math.abs((s.duration || 0) - track.duration) <= 3));
  return matches.length === 1 ? matches[0].id : null;
}
