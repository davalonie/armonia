// «Buscar» in Ajustes: where to search and download from, as in the app. Kept per browser.
export const SEARCH_SOURCE_KEY = 'armonia:search-source';
const SOURCES = ['youtube_music', 'youtube'];

export function searchSource() {
  try {
    const saved = localStorage.getItem(SEARCH_SOURCE_KEY);
    return SOURCES.includes(saved) ? saved : 'youtube_music';
  } catch { return 'youtube_music'; }
}
