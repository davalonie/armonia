import { writable } from 'svelte/store';

const LAST_VIEW_KEY = 'armonia:last-view';
const VALID_VIEWS = [...(import.meta.env?.MODE==='capacitor'?['import-review']:[]),'home', 'more', 'search', 'library', 'manual-inbox', 'import-all', 'liked', 'artists', 'playlists', 'jobs', 'settings', 'mixed', 'listening'];
const MORE_VIEWS = new Set(['more','jobs','settings','listening','manual-inbox']);

const saved = localStorage.getItem(LAST_VIEW_KEY) || 'home';
const initial = import.meta.env?.MODE === 'capacitor' ? 'home' : saved==='discover'?'home':saved==='mixed'?'library':VALID_VIEWS.includes(saved)?saved:'home';

const { subscribe, set } = writable(initial);

export const currentView = { subscribe };

// Choosing Inicio again from the navigation returns to its top level.
export const homeRoot = writable(0);

export function showView(name) {
  if (!VALID_VIEWS.includes(name)) return;
  if (name === 'home') homeRoot.update(n => n + 1);
  localStorage.setItem(LAST_VIEW_KEY, name);
  set(name);
}

export function isMoreView(name) {
  return MORE_VIEWS.has(name);
}

/** Opens Buscar with this text already searched (for example, an artist from the statistics). */
export const searchFor = writable('');
export function openSearch(text) { searchFor.set(text); showView('search'); }

export const libraryArtist = writable(null);
export function openLibraryArtist(id,name) { libraryArtist.set({id,name}); showView('library'); }

export const externalArtist = writable('');
export function openExternalArtist(id) { externalArtist.set(id); showView('search'); }
