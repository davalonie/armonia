// Labels of the fast-scroll bubble, the same rules as the app (ui/components/FastScroll.kt): computed once per list
// and order, one per item, in the order shown.
const MONTHS = 'ene feb mar abr may jun jul ago sep oct nov dic'.split(' ');

/** Initial without accent (A → A); «Ñ» keeps its own letter; numbers and symbols → «#». */
export function scrollInitial(value) {
  const initial = String(value || '').trimStart().charAt(0).toLocaleUpperCase('es');
  if (initial === 'Ñ') return initial;
  const base = initial.normalize('NFD').charAt(0);
  return /\p{L}/u.test(base) ? base : '#';
}

/** «nov 2026» from an ISO date; «—» when there is none. */
export function scrollMonth(date) {
  const [year, month] = String(date || '').slice(0, 10).split('-');
  const name = MONTHS[Number(month) - 1];
  return name && /^\d{4}$/.test(year) ? `${name} ${year}` : '—';
}

export const scrollMinutes = seconds => `${Math.floor((Number(seconds) || 0) / 60)} min`;

/** Labels for songs in the given order: added (month), artist or title (initial), duration (minutes), else position. */
export function songLabels(songs, order) {
  const key = String(order || '');
  if (key.startsWith('added') || key === 'recent') return songs.map(s => scrollMonth(s.created));
  if (key.startsWith('artist')) return songs.map(s => scrollInitial(s.artist));
  if (key.startsWith('title') || key === 'name') return songs.map(s => scrollInitial(s.title ?? s.name));
  if (key.startsWith('duration')) return songs.map(s => scrollMinutes(s.duration));
  return songs.map((_, i) => String(i + 1));
}
