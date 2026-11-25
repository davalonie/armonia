import { writable } from 'svelte/store';
import { mobile } from '../native.js';
import { createSnackbarHost } from '../phoneSnackbar.js';

export const toasts = writable([]);

// On the phone, the app's Snackbar (PhoneSnackbar.svelte): one at a time, errors for longer.
export const phoneSnackbar = createSnackbarHost();

export function showToast(message, type = 'info', action = null, {replace = null, long = type === 'error'} = {}) {
  if (mobile) { phoneSnackbar.show({message, action, long, replace}); return; }
  const id = Date.now() + Math.random();
  toasts.update(t => [{ id, message, type, action }, ...t]);
  setTimeout(() => {
    toasts.update(t => t.filter(x => x.id !== id));
  }, action ? 7000 : 3300);
}
