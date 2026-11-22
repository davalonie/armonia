import { writable } from 'svelte/store';

export const toasts = writable([]);

export function showToast(message, type = 'info', action = null) {
  const id = Date.now() + Math.random();
  toasts.update(t => [{ id, message, type, action }, ...t]);
  setTimeout(() => {
    toasts.update(t => t.filter(x => x.id !== id));
  }, action ? 7000 : 3300);
}
