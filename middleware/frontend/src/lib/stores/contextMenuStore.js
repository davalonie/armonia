import { writable } from 'svelte/store';

export const contextMenuState = writable({ visible: false, x: 0, y: 0, items: [] });

// `header` ({title, subtitle, art}) names the song the actions apply to; an item of
// {type:'rating', value, onRate} renders inline stars instead of one row per value.
// On a phone the menu floats next to the button that opened it, as the app's DropdownMenu;
// `sheet` asks for the bottom sheet the app used for some songs (SongMenuSheet).
export function showContextMenu(anchorEl, items, header=null, {sheet=false}={}) {
  // A choice made inside the menu does not reach the document, so the closing listener of the
  // last menu may still wait: without removing it, it would close this one on the same click.
  document.removeEventListener('click', closeContextMenu);
  const rect = anchorEl.getBoundingClientRect();
  const mw = 250;
  const mh = items.filter(i => i !== null).length * 42 + 16 + (header ? 72 : 0);
  let top = rect.bottom + 4;
  let left = rect.right - mw;
  if (top + mh > window.innerHeight - 8) top = rect.top - mh - 4;
  if (left < 8) left = 8;
  contextMenuState.set({ visible: true, x: left, y: Math.max(8,top), items, header, anchor:anchorEl, sheet, rect });
  setTimeout(() => document.addEventListener('click', closeContextMenu, { once: true }), 0);
  document.addEventListener('keydown', _escHandler, { once: true });
}

function _escHandler(e) {
  if (e.key === 'Escape') closeContextMenu();
}

export function closeContextMenu() {
  document.removeEventListener('click', closeContextMenu);
  contextMenuState.update(s => {s.anchor?.focus();return {...s,visible:false};});
}
