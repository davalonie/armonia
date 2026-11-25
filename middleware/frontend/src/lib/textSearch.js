// The Kotlin search (ui/components/TextSearch.kt): case and accents ignored, ñ kept apart from n,
// and every word of the query somewhere in the fields.
export const foldForSearch = s => (s || '').replace(/[ñÑ]/g, '\u0001').normalize('NFD').replace(/\p{Mn}+/gu, '').replace(/\u0001/g, 'ñ').toLowerCase();

export function matchesSearch(query, ...fields) {
  const words = foldForSearch(query).split(' ').filter(Boolean);
  if (!words.length) return true;
  const text = fields.map(foldForSearch).join('\n');
  return words.every(w => text.includes(w));
}
